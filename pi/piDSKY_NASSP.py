#!/usr/bin/python3
# Copyright (c) 2026 - Vlad Mihailescu
#
# piDSKY_NASSP.py - drives the physical DSKY hardware (Nextion display,
# alert lamp panel, keyboard) from a live Orbiter/Project Apollo - NASSP
# session, instead of a standalone yaAGC instance.
#
# piDSKY2.py (the original virtualagc piPeripheral tool) connects to a
# standalone yaAGC process over its binary channel-packet TCP protocol.
# NASSP does not expose that protocol - its Virtual AGC implementation
# is embedded directly in the vessel DLLs with no external socket at all,
# UNLESS its own (undocumented, disabled-by-default) "DSKYOut" feature is
# turned on in Config\ProjectApollo\DSKYOut.cfg on the Orbiter machine:
#
#   ENABLED = true
#   IP = <this Pi's IP address>
#   DSKYPORT = 3002
#
# DSKYOut speaks a different, much simpler protocol over UDP:
#   - Every simulated frame (while the CSM/LM has sim focus), NASSP sends
#     one JSON telemetry packet to the configured IP:DSKYPORT, with the
#     DSKY's already-decoded state: prog/verb/noun/r1/r2/r3 as text,
#     a compLight flag, a flashing flag, and a 14-flag "alarms" string.
#   - Key presses are sent back as a single ASCII byte: v n + - 0-9 c p
#     o k e r  (VERB NOUN PLUS MINUS digits CLR PRO-down PRO-up KEY-REL
#     ENTR RSET).
#
# IMPORTANT quirk, confirmed by live testing against a running NASSP
# session: NASSP's receiving socket is never bound to a fixed local
# port, so DSKYPORT (3002) is only the destination for its *outgoing*
# telemetry. The port it actually listens on is whatever the OS assigned
# it, and is only discoverable as the *source port* of an incoming
# telemetry packet. So: keypresses must be sent back to the sender
# address of the last received packet, not to DSKYPORT itself.
#
# Because NASSP already decodes prog/verb/noun/registers/lamps for us,
# this script doesn't need any of piDSKY2.py's AGC-channel/relay
# decoding (outputFromAGC, codeToString, etc.) - it just reformats
# already-decoded fields onto the same Nextion/alert-panel serial
# protocols piDSKY2.py established.
#
# Keyboard reading does NOT reuse piDSKY2.py's approach. That original
# code reads raw characters from sys.stdin/termios, which only works
# when the script's own terminal session has OS input focus - true when
# piDSKY2.py is launched locally via xterm on the Pi's own display, as
# its header comments assume. This script is meant to run headless over
# SSH, with the DSKY's Arduino (in USB-HID-keyboard mode) plugged into
# the Pi's own USB port - its keystrokes go to the Pi's local console
# input focus, never to a remote SSH session's stdin. So instead this
# reads the Arduino's HID device directly via evdev, which works
# regardless of what has console/session focus.

import argparse
import fcntl
import json
import os
import socket
import sys
import threading
import time

import serial

try:
    import evdev
    from evdev import ecodes
except ImportError:
    sys.exit(
        "This script needs the 'evdev' package to read the DSKY keyboard "
        "directly from the Linux input layer. Install it with:\n"
        "  sudo apt install python3-evdev\n"
        "(or: pip3 install evdev)"
    )

cli = argparse.ArgumentParser()
cli.add_argument("--port", help="Local UDP port to listen on for NASSP telemetry; must match DSKYPORT in NASSP's DSKYOut.cfg.", type=int, default=3002)
cli.add_argument("--kbd-device", help="Path to the DSKY keyboard's evdev device (e.g. /dev/input/event3). Auto-detected if omitted.")
cli.add_argument("--list-input-devices", help="List available evdev input devices and exit.", action="store_true")
args = cli.parse_args()

if args.list_input_devices:
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        print("%s: %s" % (dev.path, dev.name))
    sys.exit(0)

###################################################################################################
# Serial setup - same hardware protocol piDSKY2.py already established.

ser_alarm = serial.Serial('/dev/ttyAlarmPanel', baudrate=115200, timeout=1)  # Alarm Panel - native USB, not the SC16IS752 HAT; baud is ignored over USB CDC
ser_disp = serial.Serial('/dev/ttySC1', baudrate=9600, parity=serial.PARITY_NONE,
                          stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS, timeout=1)  # Display

eof = b'\xff\xff\xff'
turnON = b'3957'  # RGB565 - lit color for VERB/NOUN digits and the l1/l2/l3 divider lines
blackColor = b'0'  # RGB565 for black - the unlit state for flashing VERB/NOUN digits
dimColor = b'4226'  # RGB565 - unlit-but-visible digit segments and COMP ACTY, matching the real DSKY's EL traces (visible even when not lit)


def nextionWrite(cmd):
    ser_disp.write(cmd.encode('latin_1') + eof)


def initDisplay():
    time.sleep(2)
    # The DSKY view is page 0 in the current .HMI project (no splash page
    # exists anymore) - sent explicitly anyway to force a clean re-init of
    # the page's fields/state, not just to switch pages.
    nextionWrite('page 0')
    nextionWrite('cal.bco=' + dimColor.decode())
    # Digit/register fields start filled with their unlit-but-visible look
    # (real DSKY EL segments stay visible as dim traces even when not
    # actively lit, not truly blank) - writeReg() relights individual
    # positions to turnON as real telemetry values arrive.
    for obj in ('r10', 'r20', 'r30'):
        nextionWrite(obj + '.txt="+"')
    for obj in ('p0', 'p1', 'v0', 'v1', 'n0', 'n1',
                'r11', 'r12', 'r13', 'r14', 'r15',
                'r21', 'r22', 'r23', 'r24', 'r25',
                'r31', 'r32', 'r33', 'r34', 'r35'):
        nextionWrite(obj + '.txt="8"')
    for obj in ('p0', 'p1', 'v0', 'v1', 'n0', 'n1',
                'r10', 'r11', 'r12', 'r13', 'r14', 'r15',
                'r20', 'r21', 'r22', 'r23', 'r24', 'r25',
                'r30', 'r31', 'r32', 'r33', 'r34', 'r35'):
        nextionWrite(obj + '.pco=' + dimColor.decode())
    # l1/l2/l3 are permanently-lit panel dividers on a real DSKY, not tied
    # to any dynamic state - stay on for the whole session instead of
    # switching off once the bridge starts.
    nextionWrite('l1.pco=' + turnON.decode())
    nextionWrite('l2.pco=' + turnON.decode())
    nextionWrite('l3.pco=' + turnON.decode())
    # PROG/VERB/NOUN header labels - permanently lit once reached (like
    # l1/l2/l3), so this only ever turns them on, never off.
    nextionWrite('pl.bco=' + turnON.decode())
    nextionWrite('vl.bco=' + turnON.decode())
    nextionWrite('nl.bco=' + turnON.decode())
    ser_disp.flush()


def writeReg(prefix, value, lastValue):
    if value == lastValue:
        return
    # While VERB/NOUN is actively flashing, vnFlashingHandler() has
    # exclusive control of v0/v1/n0/n1's color - every telemetry frame
    # calls this function regardless, so without this check the two would
    # fight over the same .pco attribute (this function runs far more
    # often than the 0.75s flash timer, so its color writes would win,
    # showing the "unlit" dim color instead of the flash's true black).
    skipColor = vnFlashing and prefix in ('v', 'n')
    for i, ch in enumerate(value):
        if lastValue is not None and i < len(lastValue) and ch == lastValue[i]:
            continue
        if ch == ' ':
            # Unlit-but-visible, matching the real DSKY's EL segment traces
            # (still visible when not lit) - the sign position shows "+"
            # rather than "8" when blank.
            text = '+' if (prefix.startswith('r') and i == 0) else '8'
            color = dimColor
        else:
            text = ch
            color = turnON
        nextionWrite('%s%d.txt="%s"' % (prefix, i, text))
        if not skipColor:
            nextionWrite('%s%d.pco=%s' % (prefix, i, color.decode()))
    ser_disp.flush()


###################################################################################################
# Verb/Noun flash handling. NASSP tells us only on/off; the blink cadence
# is still ours to drive, same as piDSKY2.py's vnFlashingHandler did.

vnFlashing = False
vnCurrentlyOn = True
vnTimer = None


def vnFlashingHandler():
    global vnCurrentlyOn, vnTimer
    if not vnFlashing:
        return
    vnCurrentlyOn = not vnCurrentlyOn
    color = turnON if vnCurrentlyOn else blackColor
    for obj in ('v0', 'v1', 'n0', 'n1'):
        nextionWrite(obj + '.pco=' + color.decode())
    ser_disp.flush()
    vnTimer = threading.Timer(0.75, vnFlashingHandler)
    vnTimer.daemon = True
    vnTimer.start()


def setVnFlashing(flashing):
    global vnFlashing, vnCurrentlyOn, vnTimer
    if flashing == vnFlashing:
        return
    vnFlashing = flashing
    if flashing:
        vnCurrentlyOn = True
        vnFlashingHandler()
    else:
        if vnTimer is not None:
            vnTimer.cancel()
        # Stopping the flash always leaves VERB/NOUN steady and visible,
        # not dimmed - matches the real DSKY, and matches piDSKY2.py's
        # vnFlashingStop (its "flash off" comment there is misleading;
        # the steady/visible color it sets is correct).
        vnCurrentlyOn = True
        for obj in ('v0', 'v1', 'n0', 'n1'):
            nextionWrite(obj + '.pco=' + turnON.decode())
        ser_disp.flush()


###################################################################################################
# Alert-panel lamp mapping. Order must match NASSP's SendNetworkPacketDSKY
# "alarms" field exactly: Uplink NoAtt Stby KbRel OprErr Temp GimbalLock
# Prog Restart Tracker Vel Alt PrioDisp NoDAP. Char codes match the
# lamps dict in Alert Lamps/Driver/code.py.
ALARM_LAMP_CODES = ['3', '5', '7', 'B', '9', '2', '4', '6', '8', 'A', 'E', 'C', 'D', 'F']

lastLampState = ''


def updateLamps(alarmsField):
    global lastLampState
    bits = alarmsField.split()
    lampState = ''.join(code for code, bit in zip(ALARM_LAMP_CODES, bits) if bit == '1')
    if lampState == lastLampState:
        return
    ser_alarm.write(lampState.ljust(14, 'x').encode())
    ser_alarm.flush()
    lastLampState = lampState


###################################################################################################
# Keyboard reading via evdev. keyboard_driver.ino's hexaKeys[][] array is a
# grid of raw USB HID keyboard-usage codes (decimal), one per physical DSKY
# key, decoded here against the USB HID usage tables straight to evdev's
# KEY_* constants - this sidesteps the OS keyboard-layout/locale-dependent
# character translation that reading via a terminal would otherwise need.
#
#   row0: 87(KP+) 87(KP+) 36(7) 37(8) 38(9)  6(C)  8(E)
#   row1: 25(V)   86(KP-) 33(4) 34(5) 35(6) 19(P) 21(R)
#   row2: 17(N)   39(0)   30(1) 31(2) 32(3) 14(K)   -
#
# PRO (KEY_P) is handled specially: unlike every other key, NASSP wants
# distinct press ('p') and release ('o') events. The Arduino firmware
# always sends an instant synthetic press+release pulse regardless of how
# long the physical key is actually held (see keyboard_driver.ino's
# releaseKey(), called immediately after every press) - so a real hold
# still can't be reported, but evdev's genuine key-down/key-up events are
# used here anyway, since they're the most faithful signal available.
DSKY_KEYMAP = {
    ecodes.KEY_KPPLUS: '+', ecodes.KEY_KPMINUS: '-',
    ecodes.KEY_0: '0', ecodes.KEY_1: '1', ecodes.KEY_2: '2',
    ecodes.KEY_3: '3', ecodes.KEY_4: '4', ecodes.KEY_5: '5',
    ecodes.KEY_6: '6', ecodes.KEY_7: '7', ecodes.KEY_8: '8', ecodes.KEY_9: '9',
    ecodes.KEY_V: 'v',  # VERB
    ecodes.KEY_N: 'n',  # NOUN
    ecodes.KEY_C: 'c',  # CLR
    ecodes.KEY_R: 'r',  # RSET
    ecodes.KEY_K: 'k',  # KEY REL
    ecodes.KEY_E: 'e',  # ENTR
}
PRO_KEYCODE = ecodes.KEY_P


def findKeyboardDevice(explicitPath):
    if explicitPath:
        return evdev.InputDevice(explicitPath)
    needed = (ecodes.KEY_V, ecodes.KEY_N, ecodes.KEY_KPPLUS, PRO_KEYCODE)
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities().get(ecodes.EV_KEY, [])
        if all(code in caps for code in needed):
            return dev
    available = "\n".join("  %s: %s" % (p, evdev.InputDevice(p).name) for p in evdev.list_devices())
    sys.exit(
        "Could not auto-detect the DSKY keyboard among the available evdev "
        "input devices. Pass --kbd-device explicitly. Available devices:\n"
        + (available or "  (none found)")
    )


resetCount = 0


def handleKeyboard(sendKey, kbdDevice):
    # kbdDevice.read() returns a lazy generator - the actual non-blocking
    # read syscall only happens once iteration starts, not on this call,
    # so BlockingIOError can only be caught around the loop itself.
    global resetCount
    try:
        for event in kbdDevice.read():
            if event.type != ecodes.EV_KEY:
                continue
            if event.code == PRO_KEYCODE:
                if event.value == 1:
                    sendKey('p')
                    resetCount = 0
                elif event.value == 0:
                    sendKey('o')
                continue
            if event.value != 1:  # only fire on key-down for everything else
                continue
            ch = DSKY_KEYMAP.get(event.code)
            if ch is None:
                continue
            # 5 consecutive RSET presses exits back to the mission menu,
            # matching piDSKY2.py's own RRRRR-exit convention - same
            # gesture works whether you're in a standalone mission or
            # here in the NASSP Bridge.
            if ch == 'r':
                resetCount += 1
                if resetCount >= 5:
                    print("RSET x5 - exiting to mission menu ...")
                    # Clear any lit lamps before exiting - the alarm panel
                    # just latches whatever it was last told, so without
                    # this they'd stay lit through the menu and into
                    # whatever's launched next.
                    ser_alarm.write(''.ljust(14, 'x').encode())
                    ser_alarm.flush()
                    sys.exit(0)
            else:
                resetCount = 0
            sendKey(ch)
    except BlockingIOError:
        return


###################################################################################################
# NASSP DSKYOut UDP link.

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', args.port))
sock.setblocking(False)

nasspAddr = None  # learned from the sender of the first telemetry packet


def sendKey(ch):
    if nasspAddr is None:
        return
    sock.sendto(ch.encode(), nasspAddr)


lastProg = None
lastVerb = None
lastNoun = None
lastR1 = None
lastR2 = None
lastR3 = None
lastCompLight = None


def handleTelemetry(raw):
    global lastProg, lastVerb, lastNoun, lastR1, lastR2, lastR3, lastCompLight
    try:
        data = json.loads(raw)
    except ValueError as e:
        print("Bad telemetry packet, skipping (%s): %r" % (e, raw))
        return

    writeReg('p', data['prog'], lastProg)
    lastProg = data['prog']
    writeReg('v', data['verb'], lastVerb)
    lastVerb = data['verb']
    writeReg('n', data['noun'], lastNoun)
    lastNoun = data['noun']
    writeReg('r1', data['r1'], lastR1)
    lastR1 = data['r1']
    writeReg('r2', data['r2'], lastR2)
    lastR2 = data['r2']
    writeReg('r3', data['r3'], lastR3)
    lastR3 = data['r3']

    if data['compLight'] != lastCompLight:
        nextionWrite('cal.bco=' + (turnON if data['compLight'] == '1' else dimColor).decode())
        ser_disp.flush()
        lastCompLight = data['compLight']

    setVnFlashing(data['flashing'] == '1')
    updateLamps(data['alarms'])


###################################################################################################

def main():
    global nasspAddr

    kbdDevice = findKeyboardDevice(args.kbd_device)
    print("Reading DSKY keyboard from %s (%s)" % (kbdDevice.path, kbdDevice.name))
    # Without an exclusive grab, the kernel also delivers these same
    # keypresses to the console's normal tty input queue in parallel with
    # evdev - meaning e.g. the RSET x5 exit sequence silently piles up as
    # literal 'rrrrr' in the console's stdin buffer the whole time, then
    # gets replayed into runPiDSKY2.sh's menu prompt the moment it starts
    # reading input again after this script exits.
    kbdDevice.grab()
    flags = fcntl.fcntl(kbdDevice.fd, fcntl.F_GETFL)
    fcntl.fcntl(kbdDevice.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    initDisplay()
    print("Listening for NASSP DSKYOut telemetry on UDP :%d ..." % args.port)
    packetCount = 0
    lastHeartbeat = 0.0
    while True:
        # NASSP sends a telemetry packet every simulation frame, much
        # faster than we can push updates out over 9600-baud serial.
        # Drain the whole receive queue each pass and only act on the
        # newest packet, so we track live state instead of slowly
        # working through an ever-growing backlog of stale ones.
        latest = None
        while True:
            try:
                latest = sock.recvfrom(4096)
            except BlockingIOError:
                break

        if latest is not None:
            raw, sender = latest
            if nasspAddr is None:
                print("First telemetry packet received from %s - replies will go there." % (sender,))
            nasspAddr = sender
            packetCount += 1
            try:
                handleTelemetry(raw)
            except Exception as e:
                print("Error handling telemetry packet: %r" % (e,))

        now = time.time()
        if now - lastHeartbeat >= 1.0:
            lastHeartbeat = now
            print("[heartbeat] %d packets so far, prog=%r verb=%r noun=%r" % (
                packetCount, lastProg, lastVerb, lastNoun))

        handleKeyboard(sendKey, kbdDevice)
        time.sleep(0.05)


if __name__ == '__main__':
    main()
