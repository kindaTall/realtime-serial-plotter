# Serial Plotter

Real-time visualization of serial port data with live plotting and recording capabilities.

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install package
pip install -e .
```

## Usage

Launch the GUI application:

```bash
serial-plotter
```

Or run directly during development:

```bash
python test_gui.py
```

## Operation

1. Select serial port from dropdown (auto-detected)
2. Click "Open" to start data acquisition (115200 baud)
3. Click "Start Recording" to save data to CSV
4. Click "Open Folder" to access recordings

Serial data must be formatted as: `data: <value>\n`

Recordings are saved to: `~/serial_plotter_recordings/`

## Requirements

- Python 3.8+
- PyQt6
- pyqtgraph
- pyserial
- numpy

## License

MIT
