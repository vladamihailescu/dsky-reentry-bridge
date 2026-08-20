---
name: dsky-reentry-setup
description: Interactively walks a user through setting up the DSKY-Reentry bridge - a physical Apollo DSKY replica connected to Reentry (the Steam space flight simulator), covering everything from flashing a blank Raspberry Pi SD card through to a fully working bidirectional connection. Use this whenever the user wants to set up, install, configure, verify, or troubleshoot this DSKY-Reentry bridge project, mentions flashing a Raspberry Pi SD card for a DSKY/Apollo project, is following the dsky-reentry-bridge repo's setup guide, asks how to connect a physical DSKY to Reentry, reports that piDSKY_NASSP.py or reentryBridge.py isn't working, or says something along the lines of "this used to work but broke" in the context of this project (which likely means Reentry updated and changed something the bridge relies on). Always prefer this skill over improvising the setup from general knowledge - the actual file paths, port numbers, and enum values involved are undocumented by the game and were found by reverse-engineering, so guessing at them will waste the user's time.
---

# DSKY Reentry Bridge Setup

This skill walks a user - who may have little to no programming or general computing background - through getting a physical DSKY replica talking to Reentry. The full reference material lives at `../../../docs/setup-guide.md` (relative to this file, i.e. `docs/setup-guide.md` from the repo root) - that document is the source of truth for exact commands, file paths, and troubleshooting steps. This skill's job is to be the conversational layer on top of it: figure out where the user actually is, walk one phase at a time, and - critically - actually run the verification commands directly rather than asking the user to run them and report back. A beginner following a "run this and tell me what it says" instruction is a common place for the whole process to quietly go wrong (typos, misread output, wrong window). Running it directly removes that failure mode wherever it's technically possible.

Read `docs/setup-guide.md` in full before starting - it has the exact commands, and this file intentionally doesn't repeat them all here.

## Before starting: figure out where the user actually is

Don't assume a fresh start. Ask (a simple multiple-choice question works well):
- Hasn't started yet / SD card not flashed
- Pi is flashed and set up, haven't gotten to the software yet
- Pi software is running, working on the Windows side
- Everything was working, something broke recently
- Something specific is broken / getting an error right now

Branch based on the answer rather than walking through every phase regardless. If they say something broke *after previously working*, that's very likely a Reentry game update - jump to the **Re-discovery** section below rather than re-doing earlier phases that were already fine.

## General approach for each phase

The setup guide has six phases (SD card flashing, first boot, Pi software install, Pi-side verification, Windows setup, end-to-end verification). For each phase the user is currently on:

1. Explain what's about to happen and why, briefly - in plain language, not jargon. If a term is unavoidable (SSH, systemd service, UDP port), give a one-clause plain-language explanation the first time it comes up.
2. Where a step is something only the user can physically do (inserting an SD card, clicking through Raspberry Pi Imager's UI, enabling a setting inside the Reentry game window), give clear instructions and wait for confirmation before moving on.
3. Where a step is something that can be run on the user's behalf, run it directly instead of dictating a command for them to type:
   - Pinging the Pi to confirm it's reachable
   - SSHing to the Pi to run `install.sh`, check `systemctl status dsky-reentry-bridge`, check `journalctl` output, or check device paths like `/dev/ttyAlarmPanel`
   - Checking Python is installed on the Windows side (`py --version`)
   - Running `reentryBridge.py` (likely in the background, so the conversation can continue) and reading its output
   
   This only works if the tools being used (Bash, etc.) can actually reach the Pi - i.e. this skill is running on a machine on the same network as the Pi, or with SSH access configured to it. If SSH isn't reachable, fall back to walking the user through running commands themselves, but try the direct approach first.
4. Confirm the result actually looks right before moving to the next phase, don't just assume success. E.g. after `install.sh`, actually check that the systemd service shows `active (running)`, don't take "it printed Done" as sufficient on its own.
5. Some things genuinely can't be verified remotely - whether the physical Nextion display is actually lit, whether a physical key press registered in-game. For these, ask the user directly and take their word for it, since there's no other way to know.

Don't dump the whole setup guide as one long message. Walk it like a conversation - one phase, confirm it worked, move to the next.

## When something's broken (not "used to work")

Use the setup guide's Troubleshooting section as a diagnostic checklist, but investigate rather than just reciting it. E.g. if the display is dark, actually check the service status and logs before suggesting a TX/RX wiring issue - narrow down which of the documented failure modes actually matches what's being observed, instead of listing all of them at the user.

## Re-discovery ("it used to work but broke")

This means Reentry likely updated and silently changed something the bridge depends on (there's no official API - see the setup guide's appendix for full context on why). This part is genuinely technical (decompiling a game assembly with `ilspycmd`) - do this investigation directly rather than asking the user to run any of it themselves. The setup guide's appendix has the exact commands and the specific classes/fields/enums to re-check:

1. Confirm Reentry is actually installed and locate its install folder (commonly under a Steam library's `steamapps/common/Reentry - An Orbital Simulator/`).
2. Follow the appendix's `ilspycmd` download/decompile steps to re-check the current shape of `ExportAGCData`/`AGCOutputString` (output side) and the `TriggerButtonID` enums for both CM and LM (input side).
3. Diff what's found against what `windows/reentryBridge.py` currently hardcodes (`buildPacket()`, `CM_BUTTON_IDS`, `LM_BUTTON_IDS`, the file paths in the argparse defaults). Anything that changed is very likely the actual break.
4. Fix `reentryBridge.py` directly rather than just reporting the diff - the user came here to get it working again, not to receive a diagnostic report to act on themselves.
5. After fixing, actually re-verify against the running game and hardware where possible (same phase-6 approach as initial setup) before declaring it resolved.

## A note on tone

Several people this skill will walk through setup have never used a terminal before. Patience and plain language matter more than technical precision in most explanations - it's fine to simplify or skip the "why" of something like I2C or UART entirely unless asked, and just focus on "here's what happens next and why it matters that it works." Save the deeper technical explanations (which live in the setup guide) for anyone who asks for them.
