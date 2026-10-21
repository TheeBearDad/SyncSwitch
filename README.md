# SyncSwitch
A tiny Windows tray app that turns NVIDIA G-SYNC on and off with a hotkey or via Windows Tray.

-  Default hotkey:  `Ctrl+Alt+G` (change it any time from the tray menu)
-  Tray icon:  green  G  = on, grey  G  with a slash = off. Left-click the icon to toggle too.
-  Remembers your "on" mode:  fullscreen only, or fullscreen and windowed.

It flips the same driver setting as the "Enable G-SYNC" checkbox in NVIDIA Control Panel, using NVIDIA's own driver API (NVAPI). Nothing is injected into games.

## Set it up

1. Install  Python 3.9 or newer  from python.org. On the first installer screen, tick  "Add python.exe to PATH" .
2. Put this folder anywhere (e.g. `C:\Tools\gsync-toggle`).
3. Double-click  `build.bat` . After a minute you'll have `dist\GSyncToggle.exe`.
4. Run `GSyncToggle.exe`. The icon appears in the tray (you may need to click the `^` arrow and drag it onto the taskbar to keep it visible).


Side note: May have to toggle G-sync on from Nvidia Control Panel once before the program works. Unsure on that though. If anyone has issues report it to my GitHub.

Prefer not to build an .exe? From this folder:
```
pip install -r requirements.txt
pythonw gsync_toggle.py
```

## Using it

Right-click the tray icon for:

| Menu item | What it does |
|---|---|
| Turn G-SYNC on / off | Same as the hotkey. |
| When on, use | Fullscreen only, or Fullscreen and windowed. |
| Change hotkey... | Press any combo (needs Ctrl, Alt, Shift or Win, except F-keys, which can be used alone), then  Save . Esc cancels; "Reset to default" goes back to Ctrl+Alt+G. |
| Show notifications | The small pop-up after each toggle. |
| Start with Windows | Starts the app when you sign in (as administrator, without a UAC prompt). |
| Restart as administrator | Only shown when needed - see below. |

Settings are saved in `%APPDATA%\GSyncToggle\config.json`.

### Administrator rights
On many systems the NVIDIA driver only lets programs running as administrator change global settings. If a toggle says it needs administrator rights, choose  Restart as administrator  from the menu. Turning on  Start with Windows  while running as admin makes it start elevated automatically from then on.

### When does the change take effect?
The driver reads this setting when a game starts.  Games already running may keep their old G-SYNC state until you restart them.  To confirm it's working, turn on NVIDIA Control Panel → Display → *G-SYNC Compatible Indicator* (or *G-SYNC Indicator*) — it shows on screen whenever G-SYNC is active.

## Command line
Useful for Stream Deck buttons, shortcuts, or scripts (run from an admin prompt if required):
```
GSyncToggle.exe --toggle
GSyncToggle.exe --on            (uses your saved "on" mode)
GSyncToggle.exe --on --mode windowed
GSyncToggle.exe --off
GSyncToggle.exe --status
```

## Troubleshooting
-  "Hotkey is already in use"  – another app (Discord, GeForce Experience/NVIDIA App, OBS, Game Bar…) owns that combo. Pick a different one.
-  Win+ combos won't save  – Windows reserves most of them. Use Ctrl/Alt/Shift instead.
-  "nvapi64.dll not found"  – no NVIDIA driver is installed or the GPU isn't the active display adapter.
-  Icon shows a red "!"  – the app couldn't talk to the driver; hover the icon or check the menu for the message.
-  To remove it  – untick *Start with Windows*, choose *Exit*, and delete the folder plus `%APPDATA%\GSyncToggle`.

## Technical notes
Settings changed (IDs from NVIDIA's `NvApiDriverSettings.h`), in the driver's base profile and in the active global preset if it overrides them:

| Setting | ID | Values |
|---|---|---|
| `VRR_MODE` – "Enable G-SYNC globally" | `0x1194F158` | 0 off, 1 fullscreen only, 2 fullscreen + windowed |
| `VRRREQUESTSTATE` – "VRR requested state" | `0x1094F1F7` | same |

You can inspect both with NVIDIA Profile Inspector under the global profile if you want to double-check.
