"""Command-line interface for Serial Plotter."""

import argparse
import sys
from pathlib import Path

from serial_plotter.gui import main as gui_main


def main():
    """Main entry point for the serial plotter application."""
    parser = argparse.ArgumentParser(prog="serial-plotter")
    parser.add_argument(
        "--presentation",
        metavar="PATH",
        help="Path to presentation JSON config (enables presentation mode).",
    )
    args = parser.parse_args()

    config = None
    if args.presentation:
        from serial_plotter.presentation import (
            PresentationConfig,
            PresentationConfigError,
        )
        path = Path(args.presentation).expanduser().resolve()
        try:
            config = PresentationConfig.from_json(path)
        except FileNotFoundError as e:
            print(f"Presentation config not found: {e}", file=sys.stderr)
            return 2
        except PresentationConfigError as e:
            print(f"Invalid presentation config: {e}", file=sys.stderr)
            return 2

    gui_main(presentation_config=config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
