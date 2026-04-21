#!/usr/bin/env python3
"""Toggle bed occupancy between OCCUPIED and NOT_OCCUPIED every 5 s.

Usage:
    python toggle_occupancy.py                               # default port
    python toggle_occupancy.py /dev/cu.usbmodem1131401       # explicit port
    python toggle_occupancy.py /dev/cu.usbmodem1131401 2     # port + interval (s)

Ctrl+C to stop.
"""

import sys
import time

from sm_bedstate_driver import SMBedStateDriver, BedOccupancy

DEFAULT_PORT = "/dev/cu.usbmodem1131401"
DEFAULT_INTERVAL_S = 5.0


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_INTERVAL_S

    print(f"Toggling bed occupancy on {port} every {interval}s. Ctrl+C to stop.")

    with SMBedStateDriver(port, timeout=2.0) as sm:
        print(f"Firmware: {sm.firmware_version()}")
        states = [
            (BedOccupancy.OCCUPIED,     0.95),
            (BedOccupancy.NOT_OCCUPIED, 0.95),
        ]
        i = 0
        while True:
            state, prob = states[i % 2]
            sm.set_occupancy(state, prob, 0)
            print(f"[{time.strftime('%H:%M:%S')}] -> {state.name}")
            i += 1
            time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nstopped.")
        sys.exit(0)
