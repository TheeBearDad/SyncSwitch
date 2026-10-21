#  SyncSwitch

Turn NVIDIA G-SYNC on and off with a single hotkey, without opening NVIDIA Control Panel.

 SyncSwitch sits in your system tray. Press **Ctrl+Alt+G** (or any hotkey you choose) and G-SYNC flips on or off, with a small pop-up confirming the new state.

 Side Note: First time you use this program you may have to toggle G-Sync on in Nvidia Control Panel first. I haven't fully tested that so please let me know if this is an issue.

 When toggling G-Sync on and off your monitor will black screen for a few seconds. That is totally normal and cannot be avoided.

## Features

- **One-key toggle** with a global hotkey that works in any app or game
- **Change the hotkey** any time from the tray menu
- **Tray icon shows the state at a glance**: green **G** = on, grey slashed **G** = off
- **Remembers your preferred mode**: fullscreen only, or fullscreen and windowed
- **Start with Windows**, with no UAC prompt each time
- **Command-line options** for scripts, shortcuts and Stream Deck buttons
- **Lightweight and safe**: uses NVIDIA's own driver API (NVAPI) to change the same setting as the "Enable G-SYNC" checkbox in NVIDIA Control Panel. Nothing is injected into games.

## Requirements

- Windows 10 or 11
- An NVIDIA GPU with a G-SYNC or G-SYNC Compatible display
- A current NVIDIA driver

## Download

1. Go to the [**Releases**](../../releases) page.
2. Download ` SyncSwitch.exe` from the latest release.
3. Put it somewhere permanent, such as `C:\Tools\SyncSwitch\`, and run it.

The icon appears in your system tray. If you don't see it, click the **^** arrow near the clock and drag the icon onto the taskbar so it stays visible.

> **Windows SmartScreen warning?** Because the app isn't code-signed, Windows may show "Windows protected your PC" the first time. Click **More info → Run anyway**.

## How to use

| Action | How |
|---|---|
| Toggle G-SYNC | Press **Ctrl+Alt+G**, or left-click the tray icon |
| Open the menu | Right-click the tray icon |

### Tray menu

| Menu item | What it does |
|---|---|
| **Turn G-SYNC on / off** | Same as the hotkey |
| **When on, use** | Choose *Fullscreen only* or *Fullscreen and windowed* |
| **Change hotkey...** | Press a new key combination, then click **Save** |
| **Show notifications** | Turn the confirmation pop-ups on or off |
| **Start with Windows** | Launch automatically when you sign in |
| **Restart as administrator** | Appears only if the driver needs admin rights (see below) |
| **Refresh status** | Re-read the current state from the driver |
| **Exit** | Close the app |

### Changing the hotkey

Choose **Change hotkey...**, press the combination you want, and click **Save**.

- Combinations need **Ctrl**, **Alt**, **Shift** or **Win**. Function keys (F1–F24) can be used on their own.
- If another app already uses the combination (Discord, OBS, Xbox Game Bar, the NVIDIA app…), you'll be asked to pick another.
- Most **Win+** combinations are reserved by Windows.
- **Esc** cancels. **Reset to default** returns to Ctrl+Alt+G.

## Good to know

**Administrator rights.** On many systems the NVIDIA driver only allows programs running as administrator to change global settings. If a toggle reports that it needs admin rights, choose **Restart as administrator** from the tray menu. If you then turn on **Start with Windows**, the app will start with admin rights automatically at every sign-in, without a UAC prompt.

**When the change takes effect.** The driver reads this setting when a game launches. **Games that are already running may keep their previous G-SYNC state until you restart them.**

**Checking that it works.** In NVIDIA Control Panel, open the **Display** menu at the top and enable **G-SYNC Indicator** (or **G-SYNC Compatible Indicator**). An on-screen label then shows whenever G-SYNC is active.

## Command line

```
 SyncSwitch.exe --toggle               Toggle G-SYNC and exit
 SyncSwitch.exe --on                   Turn on (uses your saved mode)
 SyncSwitch.exe --on --mode windowed   Turn on for fullscreen and windowed
 SyncSwitch.exe --on --mode fullscreen Turn on for fullscreen only
 SyncSwitch.exe --off                  Turn off
 SyncSwitch.exe --status               Show the current state
```

Run these from an administrator prompt if your system requires admin rights.

## Settings

Settings are stored in `%APPDATA%\ SyncSwitch\config.json`. Delete that file to reset everything to defaults.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Hotkey is already in use" | Another app owns that combination. Pick a different one with **Change hotkey...** |
| Tray icon shows a red **!** | The app couldn't talk to the NVIDIA driver. Hover over the icon or open the menu for details. |
| "nvapi64.dll not found" | No NVIDIA driver is installed, or the NVIDIA GPU isn't driving your display. |
| Toggle says it needs admin rights | Use **Restart as administrator** from the tray menu. |
| G-SYNC didn't change in a game | Restart the game; the driver applies the setting at launch. |

## Uninstalling

1. Untick **Start with Windows** in the tray menu.
2. Choose **Exit**.
3. Delete ` SyncSwitch.exe` and the folder `%APPDATA%\ SyncSwitch`.

## Building from source

Requires [Python 3.9+](https://www.python.org/downloads/) with **"Add python.exe to PATH"** ticked during install.

```
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
build.bat
```

The finished program is created at `dist\ SyncSwitch.exe`.

To run it without building an .exe:

```
pip install -r requirements.txt
pythonw gsync_toggle.py
```

### Technical details

The app changes these driver settings (IDs from NVIDIA's `NvApiDriverSettings.h`) in the global driver profile:

| Setting | ID | Values |
|---|---|---|
| `VRR_MODE` – "Enable G-SYNC globally" | `0x1194F158` | 0 = off, 1 = fullscreen only, 2 = fullscreen and windowed |
| `VRRREQUESTSTATE` – "VRR requested state" | `0x1094F1F7` | same as above |

## Disclaimer

This is an independent project and is not affiliated with or endorsed by NVIDIA. G-SYNC and NVIDIA are trademarks of NVIDIA Corporation.
