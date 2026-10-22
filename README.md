# SyncSwitch

Turn NVIDIA G-SYNC on and off with a single hotkey, without opening NVIDIA Control Panel.

SyncSwitch sits in your system tray. Press **Ctrl+Alt+G** (or any hotkey you choose) and G-SYNC flips on or off, with a small pop-up confirming the new state.

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
2. Download `SyncSwitch.exe` from the latest release.
3. Put it somewhere permanent, such as `C:\Tools\SyncSwitch\`, and run it.

The icon appears in your system tray. If you don't see it, click the **^** arrow near the clock and drag the icon onto the taskbar so it stays visible.

> **Windows SmartScreen warning?** Because the app isn't code-signed, Windows may show "Windows protected your PC" the first time. Click **More info → Run anyway**.

## Build it yourself (no .exe download needed)

Prefer not to run an .exe from the internet? That's reasonable. SyncSwitch is a single, readable Python file (`syncswitch.py`), so you can look through the code and build the program on your own PC.

### 1. Install Python

1. Download **Python 3.9 or newer** from [python.org](https://www.python.org/downloads/).
2. Run the installer and tick **"Add python.exe to PATH"** on the first screen before clicking **Install Now**.

### 2. Get the source code

Either:

- **Download it:** on this page, click the green **Code** button, then **Download ZIP**, and unzip it somewhere such as `C:\Tools\SyncSwitch\`.
- **Or clone it with Git:**
  ```
  git clone https://github.com/<your-username>/<your-repo>.git
  ```

### 3. Review the code (optional)

Everything the app does is in `syncswitch.py`. It talks to the NVIDIA driver through `nvapi64.dll`, which comes with your NVIDIA driver, and to Windows for the hotkey and tray icon. It doesn't connect to the internet. The only other packages it uses are listed in `requirements.txt`:

- [pystray](https://pypi.org/project/pystray/) – the system tray icon
- [Pillow](https://pypi.org/project/pillow/) – draws the tray icon

The build also uses [PyInstaller](https://pypi.org/project/pyinstaller/) to package everything into one .exe.

### 4. Build

Double-click **`build.bat`** in the SyncSwitch folder. It installs the packages above and builds the program. After a minute or two you'll find it at:

```
dist\SyncSwitch.exe
```

Move `SyncSwitch.exe` wherever you like and run it. Because you built it yourself, Windows may still show a SmartScreen warning the first time. Click **More info → Run anyway**.

### Or run it without building an .exe

If you'd rather skip the .exe entirely, open **Command Prompt** in the SyncSwitch folder and run:

```
pip install -r requirements.txt
pythonw syncswitch.py
```

The tray icon appears just as it does with the .exe. To run it with administrator rights, open Command Prompt with **Run as administrator** first. To start it at sign-in, use **Start with Windows** from the tray menu as usual.

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
| **Show G-SYNC indicator** | Show or hide NVIDIA's on-screen label that appears while G-SYNC is active |
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

**Checking that it works.** Tick **Show G-SYNC indicator** in the tray menu. NVIDIA's on-screen label then appears whenever G-SYNC is active. Like the G-SYNC switch itself, games that are already running pick up the change after a restart. (This is the same setting as **Display → G-SYNC Indicator** in NVIDIA Control Panel.)

## Command line

```
SyncSwitch.exe --toggle                 Toggle G-SYNC and exit
SyncSwitch.exe --on                     Turn on (uses your saved mode)
SyncSwitch.exe --on --mode windowed     Turn on for fullscreen and windowed
SyncSwitch.exe --on --mode fullscreen   Turn on for fullscreen only
SyncSwitch.exe --off                    Turn off
SyncSwitch.exe --status                 Show the current state
```

Run these from an administrator prompt if your system requires admin rights.

## Settings

Settings are stored in `%APPDATA%\SyncSwitch\config.json`. Delete that file to reset everything to defaults.

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
3. Delete `SyncSwitch.exe` and the folder `%APPDATA%\SyncSwitch`.

## Technical details

The app changes these driver settings (IDs from NVIDIA's `NvApiDriverSettings.h`) in the global driver profile:

| Setting | ID | Values |
|---|---|---|
| `VRR_MODE` – "Enable G-SYNC globally" | `0x1194F158` | 0 = off, 1 = fullscreen only, 2 = fullscreen and windowed |
| `VRRREQUESTSTATE` – "VRR requested state" | `0x1094F1F7` | same as above |
| `VRROVERLAYINDICATOR` – "Display the VRR Overlay Indicator" | `0x1095F16F` | 0 = hidden, 1 = shown |

## Disclaimer

This is an independent project and is not affiliated with or endorsed by NVIDIA. G-SYNC and NVIDIA are trademarks of NVIDIA Corporation.
