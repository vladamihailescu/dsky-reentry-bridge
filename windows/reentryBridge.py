#!/usr/bin/python3
# Copyright (c) 2026 - Vlad Mihailescu
#
# reentryBridge.py - drives the physical DSKY hardware from a live Reentry
# (Wilhelmsen Studios, Steam) session, instead of a standalone yaAGC/NASSP
# instance. Runs on the WINDOWS machine (where Reentry itself runs), NOT
# on the Raspberry Pi - Reentry has no network telemetry feature, only a
# local JSON file export, so this script has to run wherever that file is
# written and forward it over the network itself.
#
# Reentry's "Computer Live Feed" setting (Settings -> General) makes it
# write two files once per second:
#   %userprofile%\AppData\LocalLow\Wilhelmsen Studios\ReEntry\Export\Apollo\outputAGC.json
#   %userprofile%\AppData\LocalLow\Wilhelmsen Studios\ReEntry\Export\Apollo\outputLGC.json
# - one for the Command Module's AGC, one for the Lunar Module's LGC, each
# with prog/verb/noun/registers as separate per-digit strings (blank when
# not displayed) plus IsInCM/IsInLM and a set of lamp booleans/ints. This
# was found by decompiling Assembly-CSharp.dll (WilhelmsenStudios.Reentry.
# Data.ExportAGCData / AGCOutputString) - there is no official documented
# format, so re-check both classes if a Reentry update changes field names
# and this script starts reading blank/wrong values.
#
# Rather than invent a new wire format to the Pi, this reformats Reentry's
# JSON onto the *exact same* UDP JSON protocol piDSKY_NASSP.py already
# expects from NASSP's DSKYOut feature (prog/verb/noun/r1/r2/r3/compLight/
# flashing/alarms as strings). That means the Pi side needs no changes at
# all - just run piDSKY_NASSP.py as usual and point this script at it
# instead of Orbiter+NASSP.
#
# Key-press input (DSKY keys -> Reentry) uses a second, separate local
# mechanism: LyraCreative.UDP.UDPReceive listens on 127.0.0.1:8051 (also
# gated by the Computer Live Feed setting) for a small JSON DataPacket
# {TargetCraft, MessageType, ID, ToPos}. Every physical DSKY key exists as
# a TriggerButtonID enum value on both computers (ApolloCockpitTools.
# TriggerButtonID for the CM's AGC*, Apollo.LunarModule.CockpitTools.
# TriggerButtonID for the LM's LGC*) - sending MessageType=PushButton
# (1) with that ID presses it, confirmed by live-testing a V37 entry.
# There is no press/release distinction in this protocol (just a single
# momentary trigger), so PRO's key-release event ('o' from the Pi) has
# nothing to map to and is ignored - matches the physical hardware anyway,
# whose Arduino firmware only ever sends instant press+release pulses,
# never a real sustained hold.

import argparse
import json
import os
import socket
import sys
import time

cli = argparse.ArgumentParser()
cli.add_argument("--pi-host", default="10.36.0.42",
                  help="IP of the Raspberry Pi running piDSKY_NASSP.py. Verify this is still correct - noted from a past session, may have changed.")
cli.add_argument("--pi-port", type=int, default=3002,
                  help="UDP port piDSKY_NASSP.py listens on (its --port, matches NASSP's DSKYPORT convention).")
cli.add_argument("--export-dir",
                  default=os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "LocalLow", "Wilhelmsen Studios", "ReEntry", "Export", "Apollo"),
                  help="Directory containing outputAGC.json / outputLGC.json.")
cli.add_argument("--poll-interval", type=float, default=0.1,
                  help="How often to re-read the export files and send an update, in seconds. Should "
                       "roughly match Reentry's own 'packets per second' Computer Live Feed setting - "
                       "otherwise fast-changing fields like COMP ACTY's blink just alias into looking "
                       "randomly stuck, since each read only catches whatever instantaneous state "
                       "happens to land at that tick. piDSKY_NASSP.py already skips re-writing any "
                       "field that hasn't changed, so polling faster only costs extra serial traffic "
                       "for things that actually toggle, not a full display re-write every time.")
cli.add_argument("--dry-run", action="store_true",
                  help="Print the packet that would be sent instead of actually sending it over UDP - useful for checking the JSON parsing/reformatting without a reachable Pi.")
args = cli.parse_args()

AGC_PATH = os.path.join(args.export_dir, "outputAGC.json")
LGC_PATH = os.path.join(args.export_dir, "outputLGC.json")

# LyraCreative.UDP.UDPReceive's hardcoded listen port (see module docstring).
REENTRY_INPUT_ADDR = ("127.0.0.1", 8051)

# DataPacket.Craft / DataPacket.MessageTypes enum values (Unity's JsonUtility
# serializes C# enums as their plain underlying int, not by name).
CRAFT_COMMAND_MODULE = 2
CRAFT_LUNAR_MODULE = 3
MESSAGE_TYPE_PUSH_BUTTON = 1

# ApolloCockpitTools.TriggerButtonID values, one per physical DSKY key -
# same char set piDSKY_NASSP.py's DSKY_KEYMAP sends back ('o', PRO's
# release, deliberately has no entry here - see module docstring).
CM_BUTTON_IDS = {
    "v": 1, "n": 2, "+": 3, "-": 4,
    "0": 5, "1": 6, "2": 7, "3": 8, "4": 9, "5": 10, "6": 11, "7": 12, "8": 13, "9": 14,
    "c": 15, "p": 16, "k": 17, "e": 18, "r": 19,
}

# Apollo.LunarModule.CockpitTools.TriggerButtonID values.
LM_BUTTON_IDS = {
    "v": 7, "n": 8, "+": 9, "-": 10,
    "0": 11, "1": 12, "2": 13, "3": 14, "4": 15, "5": 16, "6": 17, "7": 18, "8": 19, "9": 20,
    "c": 21, "p": 22, "k": 23, "e": 24, "r": 25,
}

# Must match ALARM_LAMP_CODES' order in piDSKY_NASSP.py exactly: Uplink
# NoAtt Stby KbRel OprErr Temp GimbalLock Prog Restart Tracker Vel Alt
# PrioDisp NoDAP. PrioDisp/NoDAP are always sent off - per
# dsky-alarm-panel-usb-arduino memory, those two lamps aren't populated on
# this physical board revision at all, so there's nothing to light even if
# Reentry reported them.
LAMP_FIELD_ORDER = [
    "IlluminateUplinkActy", "IlluminateNoAtt", "IlluminateStby", "IlluminateKeyRel",
    "IlluminateOprErr", "IlluminateTemp", "IlluminateGimbalLock", "IlluminateProg",
    "IlluminateRestart", "IlluminateTracker",
]
LM_ONLY_LAMP_FIELDS = ["IlluminateVel", "IlluminateAlt"]  # only present/meaningful in outputLGC.json


def readJSON(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except ValueError:
        # Reentry writes with File.WriteAllText, which isn't atomic - a read
        # can land mid-write and see a truncated/partial file. Just skip
        # this cycle, the next poll a fraction of a second later will see
        # a complete file.
        return None


def combine2(d1, d2):
    return (d1 or " ") + (d2 or " ")


def combineRegister(sign, d1, d2, d3, d4, d5):
    return (sign or " ") + (d1 or " ") + (d2 or " ") + (d3 or " ") + (d4 or " ") + (d5 or " ")


# COMP ACTY blink synthesis. Reentry's own file export is hardcoded to a
# 1-second write interval with no way to speed it up (traced into the
# decompiled source - the "packets per second" in-game setting only feeds
# a completely separate Mercury-only UDP telemetry path, unrelated to this
# file), so a poll can only ever catch whatever instantaneous on/off phase
# of the real (much faster) blink happens to land at that exact tick -
# most polls would just show it "stuck" off. Instead of relaying that raw
# coin-flip sample, treat any observed True as "the computer is busy" for
# a couple of seconds and drive our own blink locally during that window -
# piDSKY_NASSP.py already re-lights cal.bco on any change to this field,
# so it doesn't need to know the difference.
COMP_ACTY_BLINK_PERIOD = 0.75  # seconds per half-cycle, matches piDSKY_NASSP.py's own V/N flash cadence
# Live-sampled at ~10% of 1Hz reads (roughly one true hit every ~10s), not
# a fast symmetric blink - a short hold left long gaps solid-off between
# hits, which looked indistinguishable from "not flashing". Long enough to
# bridge those gaps into a continuous-looking blink instead of sparse blips.
COMP_ACTY_BUSY_HOLD = 8.0

compLightBusyUntil = 0.0


def computeCompLight(data):
    global compLightBusyUntil
    now = time.time()
    if data.get("IlluminateCompLight"):
        compLightBusyUntil = now + COMP_ACTY_BUSY_HOLD
    if now < compLightBusyUntil:
        return (int(now / COMP_ACTY_BLINK_PERIOD) % 2) == 0
    return False


def buildAlarms(data, isLM):
    bits = ["1" if data.get(f) else "0" for f in LAMP_FIELD_ORDER]
    for f in LM_ONLY_LAMP_FIELDS:
        bits.append("1" if (isLM and data.get(f)) else "0")
    bits.append("0")  # PrioDisp - lamp not populated on this hardware
    bits.append("0")  # NoDAP - lamp not populated on this hardware
    return " ".join(bits)


def buildPacket(data, isLM):
    return json.dumps({
        "prog": combine2(data.get("ProgramD1"), data.get("ProgramD2")),
        "verb": combine2(data.get("VerbD1"), data.get("VerbD2")),
        "noun": combine2(data.get("NounD1"), data.get("NounD2")),
        "r1": combineRegister(data.get("Register1Sign"), data.get("Register1D1"), data.get("Register1D2"),
                               data.get("Register1D3"), data.get("Register1D4"), data.get("Register1D5")),
        "r2": combineRegister(data.get("Register2Sign"), data.get("Register2D1"), data.get("Register2D2"),
                               data.get("Register2D3"), data.get("Register2D4"), data.get("Register2D5")),
        "r3": combineRegister(data.get("Register3Sign"), data.get("Register3D1"), data.get("Register3D2"),
                               data.get("Register3D3"), data.get("Register3D4"), data.get("Register3D5")),
        "compLight": "1" if computeCompLight(data) else "0",
        # Forced off per user direction - VERB/NOUN blinking while awaiting
        # digit entry isn't how the real DSKY behaved, so Reentry's
        # IsFlashing is deliberately never relayed here. piDSKY_NASSP.py's
        # own vnFlashingHandler is untouched, so NASSP sessions still flash
        # if that's ever wanted there.
        "flashing": "0",
        "alarms": buildAlarms(data, isLM),
    }).encode()


def pickActiveData():
    agc = readJSON(AGC_PATH)
    lgc = readJSON(LGC_PATH)
    if agc is not None and agc.get("IsInCM"):
        return agc, False
    if lgc is not None and lgc.get("IsInLM"):
        return lgc, True
    return None, None  # neither cockpit currently occupied - hold last display


def sendKeyToReentry(sock, ch, isLM):
    buttonId = (LM_BUTTON_IDS if isLM else CM_BUTTON_IDS).get(ch)
    if buttonId is None:
        return  # 'o' (PRO release) or an unrecognized char - nothing to send
    packet = json.dumps({
        "TargetCraft": CRAFT_LUNAR_MODULE if isLM else CRAFT_COMMAND_MODULE,
        "MessageType": MESSAGE_TYPE_PUSH_BUTTON,
        "ID": buttonId,
        "ToPos": 0,
    }).encode()
    sock.sendto(packet, REENTRY_INPUT_ADDR)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Bind explicitly (to an OS-assigned port) even though sendto() would
    # normally do this implicitly on first send - on Windows, recvfrom()
    # raises WSAEINVAL on a socket that has never been bound, which bites
    # in --dry-run mode specifically, since that path never calls sendto().
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)
    dest = (args.pi_host, args.pi_port)

    print("Watching %s" % args.export_dir)
    print(("Dry run - not sending" if args.dry_run else "Sending to %s:%d" % dest))

    lastKnownIsLM = False  # which button-ID map to use for keypresses when neither cockpit currently reports active
    while True:
        data, isLM = pickActiveData()
        if data is not None:
            lastKnownIsLM = isLM
            packet = buildPacket(data, isLM)
            if args.dry_run:
                print(packet.decode())
            else:
                sock.sendto(packet, dest)

        # Relay key-press replies from the Pi (piDSKY_NASSP.py sends single
        # ASCII chars back to whoever last sent it telemetry) straight into
        # Reentry's local input port.
        try:
            while True:
                reply, sender = sock.recvfrom(64)
                ch = reply.decode("ascii", errors="ignore")
                if args.dry_run:
                    print("[from Pi %s] key: %r -> would send to Reentry (isLM=%s)" % (sender, ch, lastKnownIsLM))
                else:
                    sendKeyToReentry(sock, ch, lastKnownIsLM)
        except BlockingIOError:
            pass

        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
