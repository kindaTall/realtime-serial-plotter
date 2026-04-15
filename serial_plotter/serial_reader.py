"""Serial data reader with queue-based communication."""

import os
import re
import threading
import time
import queue
import math
from pathlib import Path
from typing import Optional
import serial

DEFAULT_DATA_PREFIX = "DataStream:"
DEFAULT_MAX_DEVICES = 4

_BEDSTATE_RE = re.compile(
    r"^\s*bedstate:\s*(-?\d+)\s+change:\s*(-?\d+)\s*$"
)


def _load_env() -> dict:
    """Load configuration from .env file, falling back to defaults."""
    config = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()

    data_prefix = config.get("DATA_PREFIX", os.environ.get("DATA_PREFIX", DEFAULT_DATA_PREFIX))
    max_devices = int(config.get("MAX_DEVICES", os.environ.get("MAX_DEVICES", str(DEFAULT_MAX_DEVICES))))

    return {"data_prefix": data_prefix, "max_devices": max_devices}


ENV_CONFIG = _load_env()


class SerialReader:
    """Reads data from serial port (or dummy source) and feeds into queue."""

    def __init__(
        self,
        data_queue: queue.Queue,
        dummy_mode: bool = True,
        bridge_queue: Optional[queue.Queue] = None,
    ):
        """
        Initialize the serial reader.

        Args:
            data_queue: Queue to put parsed data into
            dummy_mode: If True, generate dummy data instead of reading serial
            bridge_queue: Optional queue receiving (bedstate, change) tuples
                parsed from lines matching `bedstate: <int> change: <int>`.
        """
        self.data_queue = data_queue
        self.bridge_queue = bridge_queue
        self.dummy_mode = dummy_mode
        self.data_prefix = ENV_CONFIG["data_prefix"]
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.serial_port = None

        # Recording
        self.recording = False
        self.record_file = None

    def start(self, port: Optional[str] = None, baud: int = 9600):
        """Start reading data in background thread."""
        if self.running:
            print("SerialReader already running")
            return

        self.running = True

        if not self.dummy_mode and port:
            try:
                self.serial_port = serial.Serial(port, baud, timeout=1)
                print(f"Serial port opened: {port} at {baud} baud")
            except serial.SerialException as e:
                print(f"Failed to open serial port {port}: {e}")
                self.running = False
                return
            except Exception as e:
                print(f"Unexpected error opening serial port: {e}")
                self.running = False
                return

        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        print(f"SerialReader started (dummy_mode={self.dummy_mode})")

    def stop(self):
        """Stop reading data."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

        if self.serial_port:
            self.serial_port.close()
            self.serial_port = None

        self.stop_recording()
        print("SerialReader stopped")

    def start_recording(self, filename: str):
        """Start recording data to file."""
        if self.recording:
            print("Already recording")
            return

        try:
            self.record_file = open(filename, 'w')
            self.recording = True
            print(f"Recording started: {filename}")
        except Exception as e:
            print(f"Failed to start recording: {e}")

    def stop_recording(self):
        """Stop recording data."""
        if not self.recording:
            return

        self.recording = False
        if self.record_file:
            self.record_file.close()
            self.record_file = None
        print("Recording stopped")

    def _read_loop(self):
        """Main reading loop (runs in background thread)."""
        if self.dummy_mode:
            self._dummy_read_loop()
        else:
            self._serial_read_loop()

    def _dummy_read_loop(self):
        """Generate dummy data for testing."""
        t = 0
        while self.running:
            # Generate sine wave with some noise
            value = 50 + 30 * math.sin(t * 0.5) + 5 * math.sin(t * 3.2)
            line = f"{self.data_prefix} {value:.2f}\n"

            # Parse and queue
            parsed = self._parse_line(line)
            if parsed is not None:
                # Record parsed value if active (CSV format)
                if self.recording and self.record_file:
                    self.record_file.write(f"{parsed}\n")
                    self.record_file.flush()

                try:
                    self.data_queue.put_nowait(parsed)
                except queue.Full:
                    # Queue full, skip this data point
                    pass

            t += 1/350
            time.sleep(1/350)  # 350 Hz to simulate real data rate

    def _serial_read_loop(self):
        """Read from actual serial port."""
        while self.running and self.serial_port:
            try:
                if self.serial_port.in_waiting:
                    line = self.serial_port.readline().decode('utf-8', errors='ignore')

                    # Parse and queue
                    parsed = self._parse_line(line)
                    if parsed is not None:
                        # Record parsed value if active (CSV format)
                        if self.recording and self.record_file:
                            self.record_file.write(f"{parsed}\n")
                            self.record_file.flush()

                        try:
                            self.data_queue.put_nowait(parsed)
                        except queue.Full:
                            pass
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"Serial read error: {e}")
                time.sleep(0.1)

    def _parse_line(self, line: str) -> Optional[float]:
        """
        Parse a line of data.

        Data format: "<DATA_PREFIX> 123.45\n"
        Bridge format: "bedstate: <int> change: <int>\n"

        Bridge lines are side-effected into self.bridge_queue (if set) and
        return None so they don't enter the float plot path.

        Args:
            line: Raw line from serial port

        Returns:
            Parsed float value or None if not a data line.
        """
        line = line.strip()

        if self.bridge_queue is not None:
            m = _BEDSTATE_RE.match(line)
            if m is not None:
                try:
                    self.bridge_queue.put_nowait((int(m.group(1)), int(m.group(2))))
                except queue.Full:
                    pass
                return None

        prefix_with_space = self.data_prefix + " "
        if not line.startswith(prefix_with_space):
            return None

        value_str = line[len(prefix_with_space):].strip()

        try:
            return float(value_str)
        except ValueError:
            return None
