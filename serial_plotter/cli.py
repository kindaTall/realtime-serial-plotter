"""Command-line interface for Serial Plotter."""

import sys
from serial_plotter.gui import main as gui_main


def main():
    """Main entry point for the serial plotter application."""
    # Launch GUI
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
