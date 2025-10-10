"""GUI for Serial Plotter using PyQt6 and pyqtgraph."""

import sys
import queue
import subprocess
import platform
from datetime import datetime
from collections import deque
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QLineEdit,
    QLabel,
)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg
import serial.tools.list_ports
import numpy as np
from serial_plotter.serial_reader import SerialReader


class SerialPlotterGUI(QMainWindow):
    """Main window for the Serial Plotter application."""

    def __init__(self):
        super().__init__()

        # Data management
        self.data_queue = queue.Queue(maxsize=1000)
        self.data_buffer = deque(maxlen=7000)  # Last 7000 points (~20s at 350Hz)
        self.time_buffer = deque(maxlen=7000)  # Corresponding time values
        self.start_time = None

        # Serial reader
        self.serial_reader = None
        self.is_connected = False

        # Recording
        self.is_recording = False

        # Plot curve
        self.plot_curve = None

        # Port scanning
        self.current_ports = []

        self.init_ui()

        # Timer for updating plot
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self.update_plot)
        self.plot_timer.start(16)  # ~60 FPS refresh rate

        # Timer for scanning ports
        self.port_scan_timer = QTimer()
        self.port_scan_timer.timeout.connect(self.scan_ports)
        self.port_scan_timer.start(1000)  # Scan every 1 second

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Serial Plotter")
        self.setGeometry(100, 100, 1200, 700)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Top control panel
        control_layout = QHBoxLayout()
        main_layout.addLayout(control_layout)

        # COM port selection
        port_label = QLabel("Port:")
        control_layout.addWidget(port_label)

        self.port_combo = QComboBox()
        self.populate_ports()
        control_layout.addWidget(self.port_combo)

        # Open button
        self.open_button = QPushButton("Open")
        self.open_button.setFixedWidth(100)
        control_layout.addWidget(self.open_button)

        # Spacer
        control_layout.addStretch()

        # Recording controls
        self.record_button = QPushButton("Start Recording")
        self.record_button.setFixedWidth(150)
        control_layout.addWidget(self.record_button)

        # File name input
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("Optional filename suffix")
        self.filename_input.setFixedWidth(200)
        control_layout.addWidget(self.filename_input)

        # Open folder button
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setFixedWidth(100)
        control_layout.addWidget(self.open_folder_button)

        # Plot widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.setLabel("left", "Value")
        self.plot_widget.setLabel("bottom", "Time", units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setTitle("Serial Data")
        main_layout.addWidget(self.plot_widget)

        # Initialize plot curve
        self.plot_curve = self.plot_widget.plot(
            pen=pg.mkPen(color='b', width=1)
        )

        # Connect signals
        self.open_button.clicked.connect(self.on_open_clicked)
        self.record_button.clicked.connect(self.on_record_clicked)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)
        self.port_combo.currentIndexChanged.connect(self.on_port_changed)

    def populate_ports(self):
        """Populate the COM port dropdown with available ports."""
        ports = serial.tools.list_ports.comports()
        self.current_ports = [port.device for port in ports]

        # Save current selection
        current_port = self.port_combo.currentData()

        # Block signals to avoid triggering on_port_changed during update
        self.port_combo.blockSignals(True)
        self.port_combo.clear()

        if ports:
            for port in ports:
                # Show port name and description
                self.port_combo.addItem(f"{port.device} - {port.description}", port.device)

            # Restore previous selection if still available
            if current_port:
                index = self.port_combo.findData(current_port)
                if index >= 0:
                    self.port_combo.setCurrentIndex(index)
        else:
            # No ports available
            self.port_combo.addItem("No ports available", None)

        self.port_combo.blockSignals(False)

    def scan_ports(self):
        """Periodically scan for port changes."""
        ports = serial.tools.list_ports.comports()
        new_port_list = [port.device for port in ports]

        # Check if ports changed
        if new_port_list != self.current_ports:
            print(f"Port list changed: {new_port_list}")
            self.populate_ports()

    def on_open_clicked(self):
        """Handle Open button click - start/stop data acquisition."""
        if not self.is_connected:
            # Start connection
            port = self.port_combo.currentData()

            # Determine if we should use dummy mode or real serial
            if port and port != "No ports available":
                # Real serial port
                dummy_mode = False
                print(f"Connecting to {port}...")
            else:
                # Dummy mode (no port selected or no ports available)
                dummy_mode = True
                print("Starting in DUMMY MODE...")

            # Create serial reader with appropriate mode
            self.serial_reader = SerialReader(self.data_queue, dummy_mode=dummy_mode)
            self.serial_reader.start(port=port, baud=115200)

            self.is_connected = True
            self.open_button.setText("Close")
        else:
            # Stop connection
            if self.serial_reader:
                self.serial_reader.stop()
                self.serial_reader = None
            self.is_connected = False
            self.open_button.setText("Open")
            print("Disconnected")

    def on_record_clicked(self):
        """Handle Start/Stop Recording button click."""
        if not self.serial_reader:
            print("Cannot record: not connected")
            return

        if not self.is_recording:
            # Start recording
            # Create recordings directory in home folder
            recordings_dir = Path.home() / "serial_plotter_recordings"
            recordings_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = self.filename_input.text()
            if suffix:
                filename = f"recording_{timestamp}_{suffix}.csv"
            else:
                filename = f"recording_{timestamp}.csv"

            filepath = recordings_dir / filename

            self.serial_reader.start_recording(str(filepath))
            self.is_recording = True
            self.record_button.setText("Stop Recording")
            print(f"Saving to: {filepath}")
        else:
            # Stop recording
            self.serial_reader.stop_recording()
            self.is_recording = False
            self.record_button.setText("Start Recording")

    def on_open_folder_clicked(self):
        """Open recordings folder in system file explorer."""
        recordings_dir = Path.home() / "serial_plotter_recordings"
        recordings_dir.mkdir(exist_ok=True)

        try:
            system = platform.system()
            if system == "Windows":
                subprocess.run(["explorer", str(recordings_dir)])
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(recordings_dir)])
            elif system == "Linux":
                subprocess.run(["xdg-open", str(recordings_dir)])
            else:
                print(f"Unsupported OS: {system}")
        except Exception as e:
            print(f"Failed to open folder: {e}")

    def on_port_changed(self, index):
        """Handle port selection change (placeholder)."""
        port = self.port_combo.currentData()
        print(f"Port changed to: {port}")

    def update_plot(self):
        """Update plot with new data from queue (called by timer)."""
        # Pull all available data from queue
        new_data = []
        try:
            while True:
                value = self.data_queue.get_nowait()
                new_data.append(value)
        except queue.Empty:
            pass

        # Process new data
        if new_data:
            # Initialize start time on first data point
            if self.start_time is None:
                self.start_time = 0
                current_time = 0
            else:
                # Estimate time based on buffer size (assuming ~20Hz)
                if self.time_buffer:
                    current_time = self.time_buffer[-1]
                else:
                    current_time = 0

            # Add data to buffers
            for value in new_data:
                current_time += 1/350  # Increment per point at 350Hz
                self.data_buffer.append(value)
                self.time_buffer.append(current_time)

            # Update plot
            if len(self.data_buffer) > 0:
                times = np.array(self.time_buffer)
                values = np.array(self.data_buffer)
                self.plot_curve.setData(times, values)

    def closeEvent(self, event):
        """Handle window close - cleanup resources."""
        print("Shutting down...")
        self.plot_timer.stop()
        self.port_scan_timer.stop()
        if self.serial_reader:
            self.serial_reader.stop()
        event.accept()


def main():
    """Main entry point for the GUI application."""
    app = QApplication(sys.argv)
    window = SerialPlotterGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
