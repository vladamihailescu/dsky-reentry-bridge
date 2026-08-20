# DSKY Reentry Bridge

Drives a physical Apollo DSKY replica from *Reentry - A Space Flight Simulator* (Steam) - bidirectional, no game mod required. Verb/noun/program/registers/lamps flow from the game to the hardware; physical key presses (VERB, NOUN, digits, ENTR, PRO, RSET, etc.) flow back into the game.

Built as a companion to [apollo-dsky-project](https://github.com/vladamihailescu/apollo-dsky-project), the physical hardware (Raspberry Pi, Nextion display, Alert Lamps panel, keyboard) this bridge drives. That repo covers the hardware build; this one covers this specific integration.

## How it works

Reentry has no official telemetry API or mod SDK. This bridge instead uses two local, undocumented mechanisms found by decompiling the game:

- **Reentry -> DSKY**: Reentry's own "Computer Live Feed" setting writes live AGC/LGC state to a JSON file once per second. A script on the Windows PC running Reentry (`windows/reentryBridge.py`) reads that file and forwards it to the Raspberry Pi.
- **DSKY -> Reentry**: physical key presses are relayed from the Pi back to that same Windows script, which sends them to a local UDP port Reentry itself listens on for exactly this purpose (used internally for its own multiplayer "Mission Control" feature, but reachable directly too).

Full technical detail on both mechanisms - exact file paths, port numbers, and the field/enum tables - is in [docs/setup-guide.md](docs/setup-guide.md).

## Setup

Full walkthrough, starting from a blank SD card: **[docs/setup-guide.md](docs/setup-guide.md)**.

Quick summary for anyone who already has a Pi with this project's hardware set up and just needs the software:
```bash
# On the Pi:
git clone https://github.com/vladamihailescu/dsky-reentry-bridge.git
cd dsky-reentry-bridge
bash pi/install.sh

# On the Windows PC running Reentry (Settings -> General -> "Computer Live Feed" enabled first):
py windows/reentryBridge.py --pi-host <pi-ip-address>
```

## Repo layout

- `pi/` - runs on the Raspberry Pi: `piDSKY_NASSP.py` (drives the Nextion display, Alert Lamps panel, and reads the DSKY keyboard), the Alert Lamps panel's udev rule, a systemd service, and an install script.
- `windows/` - runs on the PC playing Reentry: `reentryBridge.py`, the translator between Reentry's local file/UDP mechanisms and the Pi.
- `docs/` - the full setup guide, including a troubleshooting section and an appendix on re-discovering the integration if a Reentry update changes something.

## A note on fragility

Every part of this that talks to Reentry relies on undocumented internals, not a published API. A future Reentry update could silently change field names, file paths, or port numbers. The setup guide's appendix covers how this was originally found (decompiling with `ilspycmd`) and how to re-check it if something breaks.

## License

CC0 1.0 Universal - see [LICENSE](LICENSE), matching apollo-dsky-project.
