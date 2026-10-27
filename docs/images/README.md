# Showcase images

The photos used in `docs/SHOWCASE.md`. If you take new ones, overwrite these files under
the same names — nothing in the docs needs to change.

| File | What it shows |
|---|---|
| `01-ring-overview.jpg` | seven sessions on one ring, with all five state colors |
| `02-waiting-on-you.jpg` | live data: a session is waiting for an answer (waiting) |
| `03-idle-panel.jpg` | the idle panel: clock, date, weather, summary |
| `04-launcher.jpg` | the launcher's app list |
| `05-blocked.jpg` | live data: a session is waiting for a permission (blocked, red) |
| `06-3d-printed-stand.jpg` | the Dial in the 3D-printed desk stand, showing the idle panel |

## Photography tips

**Don't use a webcam** — it blows out the colors (the colored ring looks white) and
reflects. The photos above were taken with a phone.

- **Tap the display when focusing**, so the exposure is metered on it — this keeps the
  colored ring from blowing out.
- **Switch off the light above**, or shoot from slightly to the side, so the light source
  is not reflected in the round glass.
- **Shoot straight on**, so the ring stays circular and the labels stay horizontal.
- **Avoid a busy background** — the keyboard and cables are distracting.
- Format: **JPG**, about 1200-1600 px on the longer side is enough.

## Producing a particular state

The idle panel is rare in live use (because of the 45-second `idle` → `waiting`
transition there is almost always an amber segment). For photos, produce it with demo data:
stop the agent and send all-`busy` snapshots over the serial port — a few lines using
`encode_snapshot()` from `tools/session_agent/protocol.py`.
