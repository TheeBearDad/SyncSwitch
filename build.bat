@echo off
REM Builds SyncSwitch.exe (a single file in the "dist" folder).
REM Needs Python 3.9+ from python.org with "Add python.exe to PATH" ticked.
cd /d "%~dp0"

python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :error

python -m PyInstaller --noconfirm --onefile --windowed ^
    --name SyncSwitch ^
    --hidden-import pystray._win32 ^
    syncswitch.py || goto :error

echo.
echo Done: %~dp0dist\SyncSwitch.exe
pause
exit /b 0

:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
