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
    QTabWidget,
    QTabBar,
)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg
import serial.tools.list_ports
import numpy as np
from serial_plotter.serial_reader import SerialReader, ENV_CONFIG

DEVICE_COLORS = ['b', 'r', 'g', '#FF8C00']
BUFFER_SIZE = 5250  # 15s at 350Hz
TIME_AXIS = np.linspace(0, BUFFER_SIZE / 350, BUFFER_SIZE)  # fixed x-axis


class DeviceTab(QWidget):
    """Per-device controls and data management."""

    def __init__(self, plot_widget: pg.PlotWidget, color: str, label: str,
                 get_claimed_ports=None, on_connection_changed=None):
        super().__init__()
        self.plot_widget = plot_widget
        self.color = color
        self.label = label
        self._get_claimed_ports = get_claimed_ports or (lambda exclude: set())
        self._on_connection_changed = on_connection_changed

        # Data management
        self.data_queue = queue.Queue(maxsize=1000)
        self.data_buffer = deque([float('nan')] * BUFFER_SIZE, maxlen=BUFFER_SIZE)

        # Serial reader
        self.serial_reader = None
        self.is_connected = False

        # Recording
        self.is_recording = False

        # Port scanning
        self.current_ports = []

        # Plot curve
        self.plot_curve = plot_widget.plot(
            pen=pg.mkPen(color=color, width=1), name=label
        )

        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        self.setLayout(layout)

        # Port selection
        port_label = QLabel("Port:")
        layout.addWidget(port_label)

        self.port_combo = QComboBox()
        self.populate_ports()
        layout.addWidget(self.port_combo)

        # Open button
        self.open_button = QPushButton("Open")
        self.open_button.setFixedWidth(100)
        self.open_button.clicked.connect(self.on_open_clicked)
        layout.addWidget(self.open_button)

        layout.addStretch()

        # Recording controls
        self.record_button = QPushButton("Start Recording")
        self.record_button.setFixedWidth(150)
        self.record_button.clicked.connect(self.on_record_clicked)
        layout.addWidget(self.record_button)

        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("Optional filename suffix")
        self.filename_input.setFixedWidth(200)
        layout.addWidget(self.filename_input)

        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setFixedWidth(100)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)
        layout.addWidget(self.open_folder_button)

    def populate_ports(self):
        """Populate the COM port dropdown, disabling ports claimed by other tabs."""
        ports = serial.tools.list_ports.comports()
        self.current_ports = [port.device for port in ports]
        claimed = self._get_claimed_ports(exclude=self)

        current_port = self.port_combo.currentData()

        self.port_combo.blockSignals(True)
        self.port_combo.clear()

        if ports:
            model = self.port_combo.model()
            for i, port in enumerate(ports):
                self.port_combo.addItem(f"{port.device} - {port.description}", port.device)
                if port.device in claimed:
                    item = model.item(i)
                    item.setEnabled(False)
            if current_port:
                index = self.port_combo.findData(current_port)
                if index >= 0:
                    self.port_combo.setCurrentIndex(index)
        else:
            self.port_combo.addItem("No ports available", None)

        self.port_combo.blockSignals(False)

    def scan_ports(self):
        """Rescan ports if the list changed."""
        ports = serial.tools.list_ports.comports()
        new_port_list = [port.device for port in ports]
        if new_port_list != self.current_ports:
            self.populate_ports()

    def on_open_clicked(self):
        if not self.is_connected:
            port = self.port_combo.currentData()
            dummy_mode = not port or port == "No ports available"
            if dummy_mode:
                print(f"[{self.label}] Starting in DUMMY MODE...")
            else:
                print(f"[{self.label}] Connecting to {port}...")

            self.serial_reader = SerialReader(self.data_queue, dummy_mode=dummy_mode)
            self.serial_reader.start(port=port, baud=115200)
            self.is_connected = True
            self.open_button.setText("Close")
            if self._on_connection_changed:
                self._on_connection_changed()
        else:
            if self.serial_reader:
                self.serial_reader.stop()
                self.serial_reader = None
            self.is_connected = False
            self.open_button.setText("Open")
            print(f"[{self.label}] Disconnected")
            if self._on_connection_changed:
                self._on_connection_changed()

    def on_record_clicked(self):
        if not self.serial_reader:
            print(f"[{self.label}] Cannot record: not connected")
            return

        if not self.is_recording:
            recordings_dir = Path.home() / "serial_plotter_recordings"
            recordings_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = self.filename_input.text()
            if suffix:
                filename = f"recording_{self.label}_{timestamp}_{suffix}.csv"
            else:
                filename = f"recording_{self.label}_{timestamp}.csv"

            filepath = recordings_dir / filename
            self.serial_reader.start_recording(str(filepath))
            self.is_recording = True
            self.record_button.setText("Stop Recording")
            print(f"[{self.label}] Saving to: {filepath}")
        else:
            self.serial_reader.stop_recording()
            self.is_recording = False
            self.record_button.setText("Start Recording")

    def on_open_folder_clicked(self):
        recordings_dir = Path.home() / "serial_plotter_recordings"
        recordings_dir.mkdir(exist_ok=True)
        try:
            system = platform.system()
            if system == "Windows":
                subprocess.run(["explorer", str(recordings_dir)])
            elif system == "Darwin":
                subprocess.run(["open", str(recordings_dir)])
            elif system == "Linux":
                subprocess.run(["xdg-open", str(recordings_dir)])
        except Exception as e:
            print(f"Failed to open folder: {e}")

    def update(self):
        """Drain queue and update plot curve."""
        new_data = []
        try:
            while True:
                value = self.data_queue.get_nowait()
                new_data.append(value)
        except queue.Empty:
            pass

        if new_data:
            for value in new_data:
                self.data_buffer.append(value)

        values = np.array(self.data_buffer)
        self.plot_curve.setData(TIME_AXIS, values, connect="finite")

    def cleanup(self):
        """Stop reader and remove curve from plot."""
        if self.serial_reader:
            self.serial_reader.stop()
            self.serial_reader = None
        self.plot_widget.removeItem(self.plot_curve)


class SerialPlotterGUI(QMainWindow):
    """Main window for the Serial Plotter application."""

    def __init__(self):
        super().__init__()
        self.max_devices = ENV_CONFIG["max_devices"]
        self.device_tabs: list[DeviceTab] = []
        self.next_device_num = 1
        self.available_colors = list(DEVICE_COLORS)

        self._init_ui()

        # Timer for updating all plots
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self._update_all)
        self.plot_timer.start(16)  # ~60 FPS

        # Timer for scanning ports on all tabs
        self.port_scan_timer = QTimer()
        self.port_scan_timer.timeout.connect(self._scan_all_ports)
        self.port_scan_timer.start(1000)

    def _init_ui(self):
        self.setWindowTitle("Serial Plotter")
        self.setGeometry(100, 100, 1200, 700)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # Tab widget for devices
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.setFixedHeight(60)
        main_layout.addWidget(self.tab_widget)

        # Plot widget (shared)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.setLabel("left", "Value")
        self.plot_widget.setLabel("bottom", "Time", units="s")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setTitle("Serial Data")
        self.plot_widget.addLegend()
        main_layout.addWidget(self.plot_widget)

        # Add first device tab and the "+" tab
        self._add_device_tab()
        self._add_plus_tab()

    def _get_claimed_ports(self, exclude=None) -> set:
        """Return set of port devices that are connected on other tabs."""
        claimed = set()
        for tab in self.device_tabs:
            if tab is exclude:
                continue
            if tab.is_connected and tab.serial_reader and not tab.serial_reader.dummy_mode:
                port = tab.port_combo.currentData()
                if port:
                    claimed.add(port)
        return claimed

    def _next_color(self) -> str:
        if self.available_colors:
            return self.available_colors.pop(0)
        return DEVICE_COLORS[len(self.device_tabs) % len(DEVICE_COLORS)]

    def _recycle_color(self, color: str):
        if color in DEVICE_COLORS and color not in self.available_colors:
            self.available_colors.insert(DEVICE_COLORS.index(color), color)

    def _add_device_tab(self):
        if len(self.device_tabs) >= self.max_devices:
            print(f"Maximum of {self.max_devices} devices reached")
            return

        color = self._next_color()
        label = f"Device {self.next_device_num}"
        self.next_device_num += 1

        tab = DeviceTab(self.plot_widget, color, label,
                        get_claimed_ports=self._get_claimed_ports,
                        on_connection_changed=self._refresh_all_port_combos)
        self.device_tabs.append(tab)

        # Insert before the "+" tab
        insert_idx = max(self.tab_widget.count() - 1, 0)
        self.tab_widget.insertTab(insert_idx, tab, label)
        self.tab_widget.setCurrentIndex(insert_idx)

        # Hide close button on "+" tab, show on device tabs
        self._update_plus_tab_visibility()

    def _add_plus_tab(self):
        """Add the persistent '+' tab for adding new devices."""
        plus_widget = QWidget()
        self.tab_widget.addTab(plus_widget, "+")
        plus_idx = self.tab_widget.count() - 1
        # No close button on the "+" tab
        self.tab_widget.tabBar().setTabButton(plus_idx, QTabBar.ButtonPosition.RightSide, None)
        self.tab_widget.tabBar().tabBarClicked.connect(self._on_tab_clicked)

    def _on_tab_clicked(self, index: int):
        """Handle click on '+' tab to add a new device."""
        if index == self.tab_widget.count() - 1:  # Last tab is always "+"
            self._add_device_tab()

    def _close_tab(self, index: int):
        """Close a device tab."""
        # Don't close the "+" tab
        if index == self.tab_widget.count() - 1:
            return

        tab = self.device_tabs[index]
        tab.cleanup()
        self._recycle_color(tab.color)
        self.device_tabs.pop(index)
        self.tab_widget.removeTab(index)
        self._update_plus_tab_visibility()

    def _update_plus_tab_visibility(self):
        """Hide '+' tab add functionality when at max devices."""
        plus_idx = self.tab_widget.count() - 1
        if len(self.device_tabs) >= self.max_devices:
            self.tab_widget.setTabVisible(plus_idx, False)
        else:
            self.tab_widget.setTabVisible(plus_idx, True)

    def _refresh_all_port_combos(self):
        """Refresh port dropdowns on all tabs to reflect claimed ports."""
        for tab in self.device_tabs:
            tab.populate_ports()

    def _update_all(self):
        for tab in self.device_tabs:
            tab.update()

    def _scan_all_ports(self):
        for tab in self.device_tabs:
            tab.scan_ports()

    def closeEvent(self, event):
        print("Shutting down...")
        self.plot_timer.stop()
        self.port_scan_timer.stop()
        for tab in self.device_tabs:
            tab.cleanup()
        event.accept()


def main():
    """Main entry point for the GUI application."""
    app = QApplication(sys.argv)
    window = SerialPlotterGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
