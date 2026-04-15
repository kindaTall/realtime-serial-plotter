# Presentation mode — follow-ups

Things left out of the initial presentation-mode commit (`3ceddd6`). None are blockers; capture here so they don't get lost.

1. **README update** — document `--presentation PATH`, the JSON schema, and hotkeys (F / F11 fullscreen, Esc exit, ← / → step, Space pause).
2. **Aspect-ratio fill** — images/videos are letterboxed on black. Add a per-slide `"fit": "cover"` option if crop-to-fill is ever wanted.
3. **Audio per slide** — `QMediaPlayer` audio is force-muted. Add `"muted": false` knob if narration is ever needed.
4. **Advance-on-video-end** — `duration_ms` always drives the cycle; a `"advance_on_end": true` option would let video length control timing (avoids frozen-last-frame or mid-clip cuts).
5. **Tests** — no automated tests for presentation code; matches rest of repo but worth adding a headless config-validation test at minimum.
6. **Kiosk hardening for the booth day** — disable screen saver (`caffeinate -d` on macOS), pin to one display, consider disabling ⌘Q / accidental close. Not code changes, just runbook.
7. **Restart-from-UI after Esc** — pressing Esc drops to the plain plot view. Any control-panel button restarts presentation; no dedicated "start presentation" button. Fine for MVP.
