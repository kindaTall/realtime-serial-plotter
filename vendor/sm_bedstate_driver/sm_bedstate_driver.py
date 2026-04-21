"""PC-side driver for the sm_bedstate_usb_driven SM test build.

Transport: USB CDC (ESP32 USB-Serial/JTAG), exposed on macOS as /dev/cu.usbmodem*.
Protocol: line-based ASCII, '\n' terminated. See WIRE_PROTOCOL below.

Replaces the MCP3918/data-evaluation path in the test build so the SM's
CMS switching and alarming logic can be exercised deterministically
from Python. The firmware consumes values pushed here and feeds them
straight into set_bed_state() / set_bed_state_partial().

Requires pyserial (`pip install pyserial`).
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Union

import serial  # pyserial


__version__ = "0.2.0"

DEFAULT_DATA_PREFIX = "DataStream:"
DEFAULT_BEDSTATE_PREFIX = "BedState:"


# ---------------------------------------------------------------------------
# Enums — mirror component_library/bed_state/bed_state.h exactly.
# ---------------------------------------------------------------------------

class BedOccupancy(IntEnum):
    NOT_OCCUPIED = 0
    OCCUPIED     = 1
    UNKNOWN      = 2


class Activity(IntEnum):
    NONE    = 0
    LOW     = 1
    HIGH    = 2
    UNKNOWN = 3


class Switch(IntEnum):
    INACTIVE = 0
    ACTIVE   = 1


class ExitActivity(IntEnum):
    NONE    = 0
    PRESENT = 1


# ---------------------------------------------------------------------------
# Sub-state dataclasses — mirror the C structs.
# ---------------------------------------------------------------------------

@dataclass
class OccupancyState:
    state: BedOccupancy
    prob:  float
    len:   int


@dataclass
class ActivityState:
    state: Activity
    level: float
    len:   int


@dataclass
class SwitchState:
    state: Switch
    prob:  float
    len:   float  # float in the C struct, keep parity


@dataclass
class ExitActivityState:
    state: ExitActivity
    level: float
    len:   int


@dataclass
class BedState:
    occupancy:     OccupancyState
    activity:      ActivityState
    switch_:       SwitchState
    exit_activity: ExitActivityState


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SMBedStateError(Exception):
    """Base class for driver errors."""


class SMBedStateProtocolError(SMBedStateError):
    """Firmware returned an ERR reply or a malformed line."""


class SMBedStateTimeout(SMBedStateError):
    """Timed out waiting for a reply line from the firmware."""


# ---------------------------------------------------------------------------
# Pure parser — turn a firmware-emitted line into a BedState.
#
# Accepts any of these forms (all carry the same 12 trailing fields):
#   "STATE <12 fields>"        — sm_bedstate_usb GET reply
#   "BedState: <12 fields>"    — AC_SM_104D_STREAM transition print
#   "<12 fields>"              — bare, e.g. for log post-processing
# ---------------------------------------------------------------------------

def parse_bed_state(line: str) -> BedState:
    """Parse one ASCII line into a BedState. Raises SMBedStateProtocolError
    on malformed input. No I/O, no serial — pure string → dataclass."""
    text = line.strip()
    # Strip known prefixes if present.
    if text.startswith("BedState:"):
        text = text[len("BedState:"):].strip()
    elif text.startswith("STATE "):
        text = text[len("STATE "):].strip()

    parts = text.split()
    if len(parts) != 12:
        raise SMBedStateProtocolError(
            f"expected 12 fields, got {len(parts)}: {line!r}"
        )
    try:
        occ_s, occ_p, occ_l   = int(parts[0]),  float(parts[1]),  int(parts[2])
        act_s, act_lvl, act_l = int(parts[3]),  float(parts[4]),  int(parts[5])
        sw_s,  sw_p,   sw_l   = int(parts[6]),  float(parts[7]),  float(parts[8])
        ex_s,  ex_lvl, ex_l   = int(parts[9]),  float(parts[10]), int(parts[11])
    except ValueError as exc:
        raise SMBedStateProtocolError(f"field parse failed: {line!r}") from exc

    return BedState(
        occupancy     = OccupancyState(BedOccupancy(occ_s), occ_p, occ_l),
        activity      = ActivityState(Activity(act_s), act_lvl, act_l),
        switch_       = SwitchState(Switch(sw_s), sw_p, sw_l),
        exit_activity = ExitActivityState(ExitActivity(ex_s), ex_lvl, ex_l),
    )


# ---------------------------------------------------------------------------
# Stream parser — single entry point for classifying firmware output lines.
# Extends to new line types by adding dispatch branches in `parse`.
# ---------------------------------------------------------------------------

@dataclass
class DataMsg:
    """A parsed `<DATA_PREFIX> <float>` line."""
    value: float


@dataclass
class BedStateMsg:
    """A parsed `<BEDSTATE_PREFIX> <12 fields>` line."""
    value: BedState


ParsedLine = Union[DataMsg, BedStateMsg, None]


class SMStreamParser:
    """Classifier for line-based output from the SM ESP firmware.

    One entry point — `parse(line)` — returns a tagged dataclass for
    recognised lines or `None` for anything else (malformed recognised
    lines also yield `None`; use `parse_bed_state` directly if you need
    to distinguish "didn't match" from "malformed bedstate").

    Prefixes are configurable so the same parser can drive firmware
    builds that use non-default labels.
    """

    def __init__(
        self,
        data_prefix: str = DEFAULT_DATA_PREFIX,
        bedstate_prefix: str = DEFAULT_BEDSTATE_PREFIX,
    ) -> None:
        self._data_prefix = data_prefix
        self._bedstate_prefix = bedstate_prefix

    @property
    def data_prefix(self) -> str:
        return self._data_prefix

    @property
    def bedstate_prefix(self) -> str:
        return self._bedstate_prefix

    def parse(self, line: str) -> ParsedLine:
        text = line.strip()
        if not text:
            return None

        if text.startswith(self._bedstate_prefix):
            tail = text[len(self._bedstate_prefix):].strip()
            try:
                return BedStateMsg(value=parse_bed_state(tail))
            except SMBedStateProtocolError:
                return None

        data_head = self._data_prefix + " "
        if text.startswith(data_head):
            try:
                return DataMsg(value=float(text[len(data_head):].strip()))
            except ValueError:
                return None

        return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class SMBedStateDriver:
    """Drives bedstate into the sm_bedstate_usb_driven firmware over USB CDC.

    Usage:
        with SMBedStateDriver("/dev/cu.usbmodem1101") as sm:
            sm.ping()
            sm.set_occupancy(BedOccupancy.OCCUPIED, prob=0.95, length=120)
            sm.set_switch(Switch.ACTIVE)
            state = sm.get_bed_state()
    """

    # ---- lifecycle --------------------------------------------------------

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        """Configure the driver. Does not open the port — call open() or use
        as a context manager.

        Args:
            port:     serial device path (e.g. "/dev/cu.usbmodem1101").
            baudrate: ignored over USB CDC but pyserial requires a value.
            timeout:  per-read timeout in seconds.
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        """Open the serial port and verify the firmware responds to PING."""
        if self._ser is not None and self._ser.is_open:
            return
        self._ser = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._timeout,
            write_timeout=self._timeout,
        )
        # Drain any boot banner or stale bytes.
        self._ser.reset_input_buffer()
        if not self.ping():
            raise SMBedStateProtocolError("firmware did not respond to PING")

    def close(self) -> None:
        """Close the serial port. Idempotent."""
        if self._ser is not None:
            try:
                if self._ser.is_open:
                    self._ser.close()
            finally:
                self._ser = None

    def __enter__(self) -> "SMBedStateDriver":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---- health / sync ----------------------------------------------------

    def ping(self) -> bool:
        """Round-trip a PING. Returns True on OK reply within timeout."""
        try:
            reply = self._exchange("PING")
        except (SMBedStateTimeout, SMBedStateProtocolError):
            return False
        return reply == "OK"

    def firmware_version(self) -> str:
        """Return the firmware version string reported by VER."""
        reply = self._exchange("VER")
        if not reply.startswith("VER "):
            raise SMBedStateProtocolError(f"unexpected VER reply: {reply!r}")
        return reply[len("VER "):]

    # ---- granular setters (1:1 with bed_state.h) --------------------------

    def set_occupancy(
        self,
        state: BedOccupancy,
        prob:  float = 1.0,
        length: int  = 0,
    ) -> None:
        """Maps to set_bed_occupancy(state, prob, len)."""
        self._expect_ok(f"OCC {int(state)} {float(prob)} {int(length)}")

    def set_activity(
        self,
        state:  Activity,
        level:  float = 0.0,
        length: int   = 0,
    ) -> None:
        """Maps to set_activity(state, level, len)."""
        self._expect_ok(f"ACT {int(state)} {float(level)} {int(length)}")

    def set_switch(
        self,
        state:  Switch,
        prob:   float = 1.0,
        length: float = 0.0,
    ) -> None:
        """Maps to set_switch(state, prob, len). len is float on the C side."""
        self._expect_ok(f"SW {int(state)} {float(prob)} {float(length)}")

    def set_exit_activity(
        self,
        state:  ExitActivity,
        level:  float = 0.0,
        length: int   = 0,
    ) -> None:
        """Maps to set_exit_activity(state, level, len)."""
        self._expect_ok(f"EX {int(state)} {float(level)} {int(length)}")

    # ---- bulk -------------------------------------------------------------

    def set_bed_state(self, state: BedState) -> None:
        """Push a full BedState in one ALL command — maps to set_bed_state()."""
        o, a, s, e = state.occupancy, state.activity, state.switch_, state.exit_activity
        fields = (
            int(o.state),   float(o.prob),  int(o.len),
            int(a.state),   float(a.level), int(a.len),
            int(s.state),   float(s.prob),  float(s.len),
            int(e.state),   float(e.level), int(e.len),
        )
        self._expect_ok("ALL " + " ".join(repr(f) if isinstance(f, float) else str(f) for f in fields))

    def reset_to_default(self) -> None:
        """Reset firmware-side bedstate to DEFAULT_BED_STATE."""
        self._expect_ok("RESET")

    # ---- readback ---------------------------------------------------------

    def get_bed_state(self) -> BedState:
        """Query current bedstate held in firmware. Useful for test assertions."""
        reply = self._exchange("GET")
        if not reply.startswith("STATE "):
            raise SMBedStateProtocolError(f"unexpected GET reply: {reply!r}")
        return parse_bed_state(reply)

    # ---- escape hatch -----------------------------------------------------

    def send_raw(self, line: str) -> str:
        """Send an arbitrary command line, return the raw reply line.
        Intended for debugging / protocol evolution, not normal use.
        """
        return self._exchange(line)

    # ---- internals --------------------------------------------------------

    # Reply lines always start with one of these tokens. Everything else
    # (ESP_LOG output, boot banners, BedState:/DataStream: prints if the
    # firmware is also streaming) is treated as noise and skipped.
    _REPLY_PREFIXES = ("OK", "ERR ", "ERR\n", "VER ", "STATE ")

    @staticmethod
    def _is_reply(text: str) -> bool:
        if text == "OK" or text == "ERR":
            return True
        return any(text.startswith(p) for p in ("ERR ", "VER ", "STATE "))

    def _exchange(self, line: str) -> str:
        """Write a command line and return the matching reply line (stripped).

        Keeps reading lines until one starts with a known reply prefix
        (OK / ERR / VER / STATE) or the overall timeout elapses. Non-reply
        lines (logs, boot banners, interleaved streams) are discarded.
        """
        if self._ser is None or not self._ser.is_open:
            raise SMBedStateError("port not open — call open() first")
        payload = (line.rstrip("\r\n") + "\n").encode("ascii")
        self._ser.write(payload)
        self._ser.flush()

        import time
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SMBedStateTimeout(
                    f"no reply within {self._timeout}s for {line!r}"
                )
            # Temporarily clamp pyserial's per-read timeout to the remaining budget.
            self._ser.timeout = remaining
            raw = self._ser.readline()
            if not raw or not raw.endswith(b"\n"):
                raise SMBedStateTimeout(
                    f"no reply within {self._timeout}s for {line!r}"
                )
            text = raw.decode("ascii", errors="replace").strip()
            if self._is_reply(text):
                return text
            # else: noise (log line, stream print, boot banner) — keep reading.

    def _expect_ok(self, line: str) -> None:
        reply = self._exchange(line)
        if reply == "OK":
            return
        if reply.startswith("ERR "):
            raise SMBedStateProtocolError(reply[len("ERR "):])
        raise SMBedStateProtocolError(f"unexpected reply: {reply!r}")


# ---------------------------------------------------------------------------
# Wire protocol — authoritative reference for the firmware implementer.
# ---------------------------------------------------------------------------

WIRE_PROTOCOL = """
ASCII, one command per line, '\\n' terminated. Whitespace-separated tokens.
Numbers: ints as decimal, floats with '.' (e.g. 0.95). Enums sent as ints.
Replies are also line-terminated.

Commands:
    PING                                          -> OK
    VER                                           -> VER <string>
    OCC <state:int> <prob:float> <len:int>        -> OK | ERR <code>
    ACT <state:int> <level:float> <len:int>       -> OK | ERR <code>
    SW  <state:int> <prob:float> <len:float>      -> OK | ERR <code>
    EX  <state:int> <level:float> <len:int>       -> OK | ERR <code>
    ALL <occ_s> <occ_p> <occ_l>
        <act_s> <act_lvl> <act_l>
        <sw_s>  <sw_p>  <sw_l>
        <ex_s>  <ex_lvl> <ex_l>                   -> OK | ERR <code>
    GET                                           -> STATE <same 12 fields as ALL>
    RESET                                         -> OK

Error codes:
    ERR PARSE     — malformed command
    ERR RANGE     — enum/value out of range
    ERR BUSY      — firmware cannot accept input right now
    ERR UNKNOWN   — unrecognised command
"""
