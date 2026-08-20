# Setup Guide: Blank SD Card to Working Reentry Integration

This guide covers everything needed to get a physical DSKY replica talking to *Reentry - A Space Flight Simulator* (Steam), starting from a completely blank/formatted SD card.

**Assumes the physical hardware already exists and is wired up**: a Raspberry Pi, a Nextion display connected through an SC16IS752 UART-over-I2C HAT, an Alert Lamps panel connected over native USB, and a DSKY keyboard that shows up as a USB HID device. This guide does not cover building that hardware - see the main [apollo-dsky-project](https://github.com/vladamihailescu/apollo-dsky-project) repo for the physical build (PCBs, wiring, 3D-printed parts, credits).

Two machines are involved:
- **The Raspberry Pi** - drives the physical display, lamps, and keyboard.
- **A Windows PC** - runs Reentry itself, plus a small bridge script that translates between the two.

---

## Part 1 - Flash the SD card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and install it.
2. Insert the SD card into the computer that will do the flashing (any Windows/Mac/Linux machine with an SD card slot works - doesn't have to be the eventual Reentry PC).
3. Open Raspberry Pi Imager.
4. **Choose Device**: select the Pi model in use.
5. **Choose OS**: select "Raspberry Pi OS (other)" -> **"Raspberry Pi OS Lite (64-bit)"**. The Lite version is fine - the Pi runs headless, no desktop is needed.
6. **Choose Storage**: select the SD card. Double-check the right drive is selected - this step erases everything on it.
7. Before clicking "Write", click the gear/settings icon (or it may prompt automatically) to open **advanced options**, and set:
   - **Hostname**: anything memorable, e.g. `dsky`
   - **Enable SSH**: on, using password authentication
   - **Username and password**: choose a username (avoid the default `pi` if preferred - either works) and a password. Remember these.
   - **Configure wireless LAN**: enter the Wi-Fi network name and password, *if* the Pi will connect over Wi-Fi. If connecting the Pi to a router with an Ethernet cable instead, this can be left blank.
8. Click "Write" and wait for it to finish flashing and verifying.

## Part 2 - First boot

1. Put the SD card in the Pi and power it on. First boot takes a minute or two longer than usual while it resizes the filesystem and applies the settings from Part 1.
2. Find the Pi's IP address. The easiest way: check the router's connected-devices list for the hostname chosen above. Alternatively, from another computer on the same network:
   ```
   ping dsky.local
   ```
   (replace `dsky` with whatever hostname was chosen).
3. Connect over SSH from another computer:
   ```
   ssh <username>@<pi-ip-address>
   ```
   or
   ```
   ssh <username>@dsky.local
   ```
   Accept the host key prompt the first time, then enter the password set during flashing.

Everything from here through Part 3 happens over this SSH connection.

## Part 3 - Install the bridge software

1. Install git if not already present:
   ```
   sudo apt-get update
   sudo apt-get install -y git
   ```
2. Clone this repo:
   ```
   git clone https://github.com/vladamihailescu/dsky-reentry-bridge.git
   cd dsky-reentry-bridge
   ```
3. Run the installer:
   ```
   bash pi/install.sh
   ```
   This enables I2C, installs the Alert Lamps panel's udev rule, installs the required Python packages, and sets up a background service that starts the bridge automatically on every boot.
4. If the installer printed a message about I2C being enabled for the first time, reboot now:
   ```
   sudo reboot
   ```
   Reconnect over SSH after it comes back up.

## Part 4 - Verify the Pi side

Check the background service is running:
```
systemctl status dsky-reentry-bridge
```
Should show `active (running)`. If not, check the logs for the actual error:
```
journalctl -u dsky-reentry-bridge -n 50
```

At this point the Nextion display should be lit (showing dim/blank digit positions, not powered-off-looking) and the three divider lines and PROG/VERB/NOUN labels should be on. Nothing else will change until the Windows side is connected - that's expected.

## Part 5 - Set up the Windows PC

1. Install [Python](https://www.python.org/downloads/) if not already present. During installation, check the box "Add python.exe to PATH".
2. In Reentry, go to **Settings -> General** and enable **"Computer Live Feed"**.
3. Download this repo's `windows` folder onto the Windows PC (either clone the whole repo with git, or just download `windows/reentryBridge.py` directly from GitHub).
4. Open a terminal (PowerShell or Command Prompt) in that folder and run:
   ```
   py reentryBridge.py --pi-host <pi-ip-address>
   ```
   replacing `<pi-ip-address>` with the Pi's actual address from Part 2. It should print:
   ```
   Watching <path to Reentry's export folder>
   Sending to <pi-ip-address>:3002
   ```

## Part 6 - Verify end-to-end

1. With Reentry running and a mission loaded (Command Module or Lunar Module, either works), watch the physical display. Any change to the on-screen verb/noun/program/registers should appear on the physical hardware within roughly a second.
2. Press a physical DSKY key (VERB, a digit, ENTR, etc.). It should register on Reentry's own in-game DSKY as if clicked with a mouse.

If both directions work, everything is set up correctly.

## Part 7 - Running it going forward

The Pi side runs automatically on every boot - nothing to do there.

On the Windows PC, `reentryBridge.py` needs to be started manually each time (leave the terminal window open in the background while playing):
```
py reentryBridge.py --pi-host <pi-ip-address>
```

---

## Troubleshooting

**Physical display stays completely dark, not even dim/blank digits.** Check the service is actually running (`systemctl status dsky-reentry-bridge`). If it's running but the display is still dark, check the Nextion HAT's TX/RX wiring hasn't come loose - this has happened before from handling wires nearby, and it looks identical to a software failure from the outside.

**Alert Lamps panel doesn't light up / `/dev/ttyAlarmPanel` doesn't exist.** Unplug and replug the panel's USB cable - the udev rule only creates the stable device path on a fresh USB "add" event, not retroactively for a device that was already plugged in when the rule was installed.

**Pi has intermittently stopped responding, or the keyboard/panel randomly disappears.** Check `dmesg` for `Undervoltage detected!`. This points to the Pi's power supply, not the software - use the official/an adequately rated USB power supply, or a powered USB hub for the peripherals.

**`reentryBridge.py` runs but nothing updates on the display.** Confirm "Computer Live Feed" is actually enabled in Reentry's settings, and that a mission is loaded (sitting at the game's main menu produces no export data). Also confirm the Pi's IP address is current - `--pi-host` needs to match whatever the Pi's address actually is right now, which can change if the router reassigns it.

**Physical key presses don't do anything in-game.** Confirm `reentryBridge.py` is actually running (not just the Pi-side service) - the physical-key-to-game-input path goes through this script, not directly from the Pi. Also confirm Reentry's own window has focus/is the active application, in case its input handling requires that.

**Everything worked before, stopped after a Reentry update.** See the appendix below - Reentry exposes no official API for any of this, so a game update could change the exact file paths, field names, or port numbers this bridge relies on.

---

## Appendix - Re-discovering the integration after a Reentry update

Everything this bridge relies on was found by decompiling Reentry's own code, not from any published documentation. If a game update breaks something, re-checking the actual current code is more reliable than guessing at what changed.

### Tools needed

Reentry is a Mono-based Unity game (not IL2CPP), so its C# code can be decompiled back into readable source with `ilspycmd`, without needing a full Visual Studio install or the .NET SDK - just the plain .NET runtime, which recent Windows systems typically already have.

Download `ilspycmd` (it's a NuGet package, which is just a zip file):
1. Check the latest version number at `https://api.nuget.org/v3-flatcontainer/ilspycmd/index.json`.
2. Download `https://api.nuget.org/v3-flatcontainer/ilspycmd/<version>/ilspycmd.<version>.nupkg`.
3. Extract it (rename to `.zip` first, or use any zip tool - a `.nupkg` file is a zip file).
4. The tool lives at `tools/net10.0/any/ilspycmd.dll` inside the extracted folder (the exact `net10.0` part may differ by version).

Run it against Reentry's assembly:
```
dotnet <path-to>/ilspycmd.dll -t <FullyQualifiedTypeName> "<Reentry install folder>\ReEntry_Data\Managed\Assembly-CSharp.dll"
```
The Reentry install folder is normally under the Steam library, e.g. `...\steamapps\common\Reentry - An Orbital Simulator\`.

Useful commands:
- `-l c` / `-l e` after the assembly path lists every class / enum name in the whole game - good for finding a renamed class.
- `-p -o <output-folder>` decompiles the *entire* game into readable `.cs` files in that folder - slower, but then any text search tool (e.g. `grep -rl SomeMethodName <output-folder>`) can find exactly which class calls what, which a single-type decompile can't answer.

### What to re-check, and what it currently looks like (as of this writing)

**Output (game -> DSKY)**: `WilhelmsenStudios.Reentry.Data.ExportAGCData` and `AGCOutputString` - writes to `%AppData%\LocalLow\Wilhelmsen Studios\ReEntry\Export\Apollo\outputAGC.json` (Command Module) and `outputLGC.json` (Lunar Module) once per second. If `reentryBridge.py` stops picking up changes, re-decompile these two classes and compare field names against `reentryBridge.py`'s `buildPacket()` function.

**Input (DSKY keys -> game)**: `LyraCreative.UDP.UDPReceive` listens on local UDP port 8051 for a JSON `{"TargetCraft": <int>, "MessageType": <int>, "ID": <int>, "ToPos": <int>}` packet. `MessageType` 1 = push a button; the `ID` values come from `ApolloCockpitTools.TriggerButtonID` (Command Module) and `Apollo.LunarModule.CockpitTools.TriggerButtonID` (Lunar Module) - plain enums, so a value's actual number is just its position in the list (starting at 0 for the first entry). If key presses stop working, re-decompile both `TriggerButtonID` enums and compare against `reentryBridge.py`'s `CM_BUTTON_IDS`/`LM_BUTTON_IDS` dictionaries - a game update that reorders or adds entries to either enum would silently shift every number after it.

**The gating setting**: both of the above only run if Reentry's "Computer Live Feed" setting is on, tracked as `GST_ComputerLiveFeed` in `%AppData%\LocalLow\Wilhelmsen Studios\ReEntry\System\game.rsf` (plain JSON). If this key ever gets renamed, the setting will still be visible and toggleable in Reentry's own Settings menu even if this specific storage key name changes - the important thing is just that it's turned on, not the exact key name.
