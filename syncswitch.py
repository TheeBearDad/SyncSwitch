"""
SyncSwitch
==========

A small Windows tray app that turns NVIDIA G-SYNC on and off with a global
hotkey (default Ctrl+Alt+G). The hotkey can be changed from the tray menu.

How it works
------------
NVIDIA keeps the "Enable G-SYNC" switch in its driver settings database (the
same place NVIDIA Control Panel and NVIDIA Profile Inspector write to). This
app talks to that database through NVAPI, NVIDIA's own driver API, which ships
with every GeForce driver as nvapi64.dll. Nothing is patched or injected.

The two settings it changes (IDs from NVIDIA's NvApiDriverSettings.h):
    VRR_MODE         0x1194F158  "Enable G-SYNC globally"
    VRRREQUESTSTATE  0x1094F1F7  "VRR requested state"
Values: 0 = off, 1 = fullscreen only, 2 = fullscreen and windowed.

The tray menu can also show or hide the on-screen G-SYNC indicator:
    VRROVERLAYINDICATOR  0x1095F16F  "Display the VRR Overlay Indicator"

Command line (handy for scripts / Stream Deck etc.):
    SyncSwitch.exe --toggle | --on | --off | --status
    SyncSwitch.exe --on --mode windowed
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from ctypes import (
    CFUNCTYPE, POINTER, Structure, Union, byref, c_char, c_int, c_long,
    c_size_t, c_ssize_t, c_uint, c_uint8, c_uint16, c_uint32, c_uint64,
    c_void_p, c_wchar_p, sizeof,
)
from xml.sax.saxutils import escape as xml_escape

APP_NAME = "SyncSwitch"
APP_TITLE = "SyncSwitch"
IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------------------
# G-SYNC modes
# ---------------------------------------------------------------------------
MODE_OFF = 0
MODE_FULLSCREEN = 1
MODE_FULLSCREEN_WINDOWED = 2
MODE_NAMES = {
    MODE_OFF: "off",
    MODE_FULLSCREEN: "fullscreen only",
    MODE_FULLSCREEN_WINDOWED: "fullscreen and windowed",
}

# ---------------------------------------------------------------------------
# NVAPI definitions (verified against NVIDIA's public nvapi.h /
# nvapi_interface.h / NvApiDriverSettings.h)
# ---------------------------------------------------------------------------
NVAPI_OK = 0
NVAPI_NVIDIA_DEVICE_NOT_FOUND = -6
NVAPI_INVALID_USER_PRIVILEGE = -137
NVAPI_SETTING_NOT_FOUND = -160

VRR_MODE_ID = 0x1194F158          # "Enable G-SYNC globally"
VRR_REQUEST_STATE_ID = 0x1094F1F7  # "VRR requested state"
GSYNC_SETTING_IDS = (VRR_MODE_ID, VRR_REQUEST_STATE_ID)
VRR_INDICATOR_ID = 0x1095F16F      # "Display the VRR Overlay Indicator" (0 = off, 1 = on)

NVDRS_DWORD_TYPE = 0
NVDRS_CURRENT_PROFILE_LOCATION = 0

_FUNC_IDS = {
    "Initialize": 0x0150E828,
    "Unload": 0xD22BDD7E,
    "GetErrorMessage": 0x6C2D048C,
    "DRS_CreateSession": 0x0694D52E,
    "DRS_DestroySession": 0xDAD9CFF8,
    "DRS_LoadSettings": 0x375DBD6B,
    "DRS_SaveSettings": 0xFCBC7E14,
    "DRS_GetBaseProfile": 0xDA8466A0,
    "DRS_GetCurrentGlobalProfile": 0x617BFF9F,
    "DRS_GetSetting": 0x73BF8338,
    "DRS_SetSetting": 0x577DD202,
}

NVAPI_UNICODE_STRING_MAX = 2048
NVAPI_BINARY_DATA_MAX = 4096


class NVDRS_BINARY_SETTING(Structure):
    _pack_ = 4
    _fields_ = [
        ("valueLength", c_uint32),
        ("valueData", c_uint8 * NVAPI_BINARY_DATA_MAX),
    ]


class _NVDRS_VALUE(Union):
    _pack_ = 4
    _fields_ = [
        ("u32", c_uint32),
        ("binary", NVDRS_BINARY_SETTING),
        ("wsz", c_uint16 * NVAPI_UNICODE_STRING_MAX),
        ("u64", c_uint64),
    ]


class NVDRS_SETTING(Structure):
    """NVDRS_SETTING_V1 (#pragma pack(4) in nvapi.h)."""
    _pack_ = 4
    _fields_ = [
        ("version", c_uint32),
        ("settingName", c_uint16 * NVAPI_UNICODE_STRING_MAX),
        ("settingId", c_uint32),
        ("settingType", c_int),
        ("settingLocation", c_int),
        ("isCurrentPredefined", c_uint32),
        ("isPredefinedValid", c_uint32),
        ("predefined", _NVDRS_VALUE),
        ("current", _NVDRS_VALUE),
    ]


# MAKE_NVAPI_VERSION(NVDRS_SETTING_V1, 1)
NVDRS_SETTING_VER1 = sizeof(NVDRS_SETTING) | (1 << 16)


class NvApiError(Exception):
    def __init__(self, func: str, status: int | None, text: str):
        self.func = func
        self.status = status
        super().__init__(f"{func} failed: {text}" + (f" ({status})" if status is not None else ""))


class NeedsAdminError(NvApiError):
    pass


class NvApi:
    """Minimal ctypes binding for the NVAPI driver-settings (DRS) functions."""

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise NvApiError("NVAPI", None, "only available on Windows")
        dll_name = "nvapi64.dll" if sizeof(c_void_p) == 8 else "nvapi.dll"
        try:
            dll = ctypes.CDLL(dll_name)
        except OSError:
            raise NvApiError("NVAPI", None,
                             f"{dll_name} not found - is an NVIDIA driver installed?")
        qi = dll.nvapi_QueryInterface
        qi.restype = c_void_p
        qi.argtypes = [c_uint32]

        def bind(name: str, *argtypes):
            ptr = qi(_FUNC_IDS[name])
            if not ptr:
                raise NvApiError(f"NvAPI_{name}", None, "not supported by this driver")
            return CFUNCTYPE(c_int, *argtypes)(ptr)

        H = c_void_p
        self._initialize = bind("Initialize")
        self._get_error_message = bind("GetErrorMessage", c_int, POINTER(c_char * 64))
        self._create_session = bind("DRS_CreateSession", POINTER(H))
        self._destroy_session = bind("DRS_DestroySession", H)
        self._load_settings = bind("DRS_LoadSettings", H)
        self._save_settings = bind("DRS_SaveSettings", H)
        self._get_base_profile = bind("DRS_GetBaseProfile", H, POINTER(H))
        self._get_global_profile = bind("DRS_GetCurrentGlobalProfile", H, POINTER(H))
        self._get_setting = bind("DRS_GetSetting", H, H, c_uint32, POINTER(NVDRS_SETTING))
        self._set_setting = bind("DRS_SetSetting", H, H, POINTER(NVDRS_SETTING))

        self.check("NvAPI_Initialize", self._initialize())

    # -- helpers ------------------------------------------------------------
    def error_text(self, status: int) -> str:
        buf = (c_char * 64)()
        if self._get_error_message(status, byref(buf)) == NVAPI_OK:
            return buf.value.decode("ascii", "replace")
        return "unknown error"

    def check(self, func: str, status: int) -> None:
        if status == NVAPI_OK:
            return
        if status == NVAPI_INVALID_USER_PRIVILEGE:
            raise NeedsAdminError(func, status, "administrator rights are required")
        if status == NVAPI_NVIDIA_DEVICE_NOT_FOUND:
            raise NvApiError(func, status, "no NVIDIA GPU driving a display was found")
        raise NvApiError(func, status, self.error_text(status))

    @contextlib.contextmanager
    def session(self):
        h = c_void_p()
        self.check("NvAPI_DRS_CreateSession", self._create_session(byref(h)))
        try:
            self.check("NvAPI_DRS_LoadSettings", self._load_settings(h))
            yield h
        finally:
            self._destroy_session(h)

    def base_profile(self, session) -> c_void_p:
        p = c_void_p()
        self.check("NvAPI_DRS_GetBaseProfile", self._get_base_profile(session, byref(p)))
        return p

    def global_profile(self, session) -> c_void_p | None:
        p = c_void_p()
        if self._get_global_profile(session, byref(p)) != NVAPI_OK or not p.value:
            return None
        return p

    def get_dword(self, session, profile, setting_id: int) -> tuple[int, int] | None:
        """Returns (value, location) or None if the setting isn't set anywhere."""
        s = NVDRS_SETTING()
        s.version = NVDRS_SETTING_VER1
        status = self._get_setting(session, profile, setting_id, byref(s))
        if status == NVAPI_SETTING_NOT_FOUND:
            return None
        self.check("NvAPI_DRS_GetSetting", status)
        return s.current.u32, s.settingLocation

    def set_dword(self, session, profile, setting_id: int, value: int) -> None:
        s = NVDRS_SETTING()
        s.version = NVDRS_SETTING_VER1
        s.settingId = setting_id
        s.settingType = NVDRS_DWORD_TYPE
        s.current.u32 = value
        self.check("NvAPI_DRS_SetSetting", self._set_setting(session, profile, byref(s)))

    def save(self, session) -> None:
        self.check("NvAPI_DRS_SaveSettings", self._save_settings(session))


class GSyncController:
    """Reads and writes the global G-SYNC mode."""

    def __init__(self) -> None:
        self.api = NvApi()

    def _target_profiles(self, s, setting_id: int = VRR_MODE_ID) -> list:
        # The base profile holds the global switch. If the active global
        # preset has its own copy of the setting, it overrides the base
        # profile, so keep that one in sync too.
        profiles = [self.api.base_profile(s)]
        g = self.api.global_profile(s)
        if g is not None and g.value != profiles[0].value:
            found = self.api.get_dword(s, g, setting_id)
            if found and found[1] == NVDRS_CURRENT_PROFILE_LOCATION:
                profiles.append(g)
        return profiles

    def read_indicator(self) -> bool:
        """True if the on-screen G-SYNC indicator is enabled."""
        with self.api.session() as s:
            base = self.api.base_profile(s)
            found = self.api.get_dword(s, base, VRR_INDICATOR_ID)
            g = self.api.global_profile(s)
            if g is not None and g.value != base.value:
                own = self.api.get_dword(s, g, VRR_INDICATOR_ID)
                if own and own[1] == NVDRS_CURRENT_PROFILE_LOCATION:
                    found = own
            return bool(found and found[0])  # not set anywhere = hidden

    def write_indicator(self, enabled: bool) -> None:
        with self.api.session() as s:
            for profile in self._target_profiles(s, VRR_INDICATOR_ID):
                self.api.set_dword(s, profile, VRR_INDICATOR_ID, 1 if enabled else 0)
            self.api.save(s)

    def read_mode(self) -> int:
        with self.api.session() as s:
            base = self.api.base_profile(s)
            found = (self.api.get_dword(s, base, VRR_MODE_ID)
                     or self.api.get_dword(s, base, VRR_REQUEST_STATE_ID))
            g = self.api.global_profile(s)
            if g is not None and g.value != base.value:
                own = self.api.get_dword(s, g, VRR_MODE_ID)
                if own and own[1] == NVDRS_CURRENT_PROFILE_LOCATION:
                    found = own  # active global preset overrides the base profile
            if found is None:
                return MODE_FULLSCREEN  # driver default
            value = found[0]
            return value if value in MODE_NAMES else MODE_FULLSCREEN

    def write_mode(self, mode: int) -> None:
        if mode not in MODE_NAMES:
            raise ValueError(f"invalid G-SYNC mode {mode}")
        with self.api.session() as s:
            for profile in self._target_profiles(s):
                for setting_id in GSYNC_SETTING_IDS:
                    self.api.set_dword(s, profile, setting_id, mode)
            self.api.save(s)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
DEFAULT_HOTKEY = {"modifiers": MOD_CONTROL | MOD_ALT, "vk": ord("G")}


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def default_config() -> dict:
    return {"hotkey": dict(DEFAULT_HOTKEY), "on_mode": MODE_FULLSCREEN, "notifications": True}


def load_config(path: str | None = None) -> dict:
    path = path or config_path()
    cfg = default_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return cfg
    hk = data.get("hotkey")
    if (isinstance(hk, dict) and isinstance(hk.get("vk"), int) and 0 < hk["vk"] < 256
            and isinstance(hk.get("modifiers"), int)):
        cfg["hotkey"] = {"modifiers": hk["modifiers"] & 0xF, "vk": hk["vk"]}
    if data.get("on_mode") in (MODE_FULLSCREEN, MODE_FULLSCREEN_WINDOWED):
        cfg["on_mode"] = data["on_mode"]
    if isinstance(data.get("notifications"), bool):
        cfg["notifications"] = data["notifications"]
    return cfg


def save_config(cfg: dict, path: str | None = None) -> None:
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Hotkey naming
# ---------------------------------------------------------------------------
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_ESCAPE = 0x1B
MODIFIER_VKS = {VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN,
                0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}

_VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "Caps Lock",
    0x1B: "Esc", 0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End",
    0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2C: "Print Screen", 0x2D: "Insert", 0x2E: "Delete", 0x5D: "Menu",
    0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /",
    0x90: "Num Lock", 0x91: "Scroll Lock",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
    0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}


def is_function_key(vk: int) -> bool:
    return 0x70 <= vk <= 0x87  # F1-F24


def vk_name(vk: int) -> str:
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if is_function_key(vk):
        return f"F{vk - 0x6F}"
    if 0x60 <= vk <= 0x69:
        return f"Num {vk - 0x60}"
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if IS_WINDOWS:
        try:
            user32 = ctypes.WinDLL("user32")
            scan = user32.MapVirtualKeyW(vk, 0)
            buf = ctypes.create_unicode_buffer(64)
            if scan and user32.GetKeyNameTextW(scan << 16, buf, 64):
                return buf.value
        except OSError:
            pass
    return f"Key 0x{vk:02X}"


def format_hotkey(modifiers: int, vk: int) -> str:
    parts = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if modifiers & MOD_WIN:
        parts.append("Win")
    parts.append(vk_name(vk))
    return "+".join(parts)


def hotkey_is_valid(modifiers: int, vk: int) -> tuple[bool, str]:
    if vk in MODIFIER_VKS:
        return False, "Finish with a regular key, not just a modifier."
    if not modifiers and not is_function_key(vk):
        return False, "Add Ctrl, Alt, Shift or Win (F-keys may be used alone)."
    return True, ""


# ---------------------------------------------------------------------------
# Global hotkey listener (Win32 RegisterHotKey - no keyboard hooks)
# ---------------------------------------------------------------------------
class MSG(Structure):
    _fields_ = [
        ("hwnd", c_void_p), ("message", c_uint), ("wParam", c_size_t),
        ("lParam", c_ssize_t), ("time", c_uint32), ("pt_x", c_long),
        ("pt_y", c_long), ("lPrivate", c_uint32),
    ]


class HotkeyListener(threading.Thread):
    WM_HOTKEY = 0x0312
    WM_APP_REBIND = 0x8001
    WM_APP_UNBIND = 0x8002
    WM_APP_QUIT = 0x8003
    HOTKEY_ID = 1

    def __init__(self, on_hotkey) -> None:
        super().__init__(name="hotkeys", daemon=True)
        self.on_hotkey = on_hotkey
        self._ready = threading.Event()
        self._replies: queue.Queue = queue.Queue()
        self._call_lock = threading.Lock()
        self._pending = (0, 0)
        self._thread_id = 0
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.RegisterHotKey.argtypes = [c_void_p, c_int, c_uint, c_uint]
        u.UnregisterHotKey.argtypes = [c_void_p, c_int]
        u.GetMessageW.argtypes = [POINTER(MSG), c_void_p, c_uint, c_uint]
        u.GetMessageW.restype = c_int
        u.PeekMessageW.argtypes = [POINTER(MSG), c_void_p, c_uint, c_uint, c_uint]
        u.PostThreadMessageW.argtypes = [c_uint32, c_uint, c_size_t, c_ssize_t]
        self.user32 = u
        self.kernel32 = ctypes.WinDLL("kernel32")

    def run(self) -> None:
        msg = MSG()
        self._thread_id = self.kernel32.GetCurrentThreadId()
        self.user32.PeekMessageW(byref(msg), None, 0, 0, 0)  # create the queue
        self._ready.set()
        registered = False
        while self.user32.GetMessageW(byref(msg), None, 0, 0) > 0:
            if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                threading.Thread(target=self.on_hotkey, daemon=True).start()
            elif msg.message == self.WM_APP_REBIND:
                if registered:
                    self.user32.UnregisterHotKey(None, self.HOTKEY_ID)
                mods, vk = self._pending
                ok = bool(self.user32.RegisterHotKey(None, self.HOTKEY_ID,
                                                     mods | MOD_NOREPEAT, vk))
                registered = ok
                self._replies.put(ok)
            elif msg.message == self.WM_APP_UNBIND:
                if registered:
                    self.user32.UnregisterHotKey(None, self.HOTKEY_ID)
                registered = False
                self._replies.put(True)
            elif msg.message == self.WM_APP_QUIT:
                break
        if registered:
            self.user32.UnregisterHotKey(None, self.HOTKEY_ID)

    def _call(self, message: int) -> bool:
        self._ready.wait(5)
        while not self._replies.empty():
            self._replies.get_nowait()
        if not self.user32.PostThreadMessageW(self._thread_id, message, 0, 0):
            return False
        try:
            return self._replies.get(timeout=3)
        except queue.Empty:
            return False

    def register(self, modifiers: int, vk: int) -> bool:
        with self._call_lock:
            self._pending = (modifiers, vk)
            return self._call(self.WM_APP_REBIND)

    def unregister(self) -> None:
        with self._call_lock:
            self._call(self.WM_APP_UNBIND)

    def stop(self) -> None:
        if self._thread_id:
            self.user32.PostThreadMessageW(self._thread_id, self.WM_APP_QUIT, 0, 0)


# ---------------------------------------------------------------------------
# Windows helpers: admin, single instance, start with Windows
# ---------------------------------------------------------------------------
CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def launch_command() -> tuple[str, str]:
    """(program, arguments) that start this app without a console."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    return exe, f'"{os.path.abspath(__file__)}"'


def relaunch_as_admin() -> bool:
    program, args = launch_command()
    shell32 = ctypes.WinDLL("shell32")
    shell32.ShellExecuteW.restype = c_void_p
    shell32.ShellExecuteW.argtypes = [c_void_p, c_wchar_p, c_wchar_p, c_wchar_p,
                                      c_wchar_p, c_int]
    rc = shell32.ShellExecuteW(None, "runas", program, (args + " --relaunched").strip(),
                               None, 1)
    return (rc or 0) > 32


def acquire_single_instance(wait_seconds: float = 0):
    """Returns a mutex handle, or None if another instance is already running.
    With wait_seconds, keeps trying (used when restarting as administrator)."""
    import time

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = c_void_p
    k32.CreateMutexW.argtypes = [c_void_p, c_int, c_wchar_p]
    k32.CloseHandle.argtypes = [c_void_p]
    deadline = time.monotonic() + wait_seconds
    while True:
        handle = k32.CreateMutexW(None, False, f"Local\\{APP_NAME}_single_instance")
        if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
            return handle
        k32.CloseHandle(handle)
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)


def startup_enabled() -> bool:
    return _schtasks("/Query", "/TN", APP_NAME).returncode == 0


def build_task_xml(program: str, args: str, user: str) -> str:
    # A scheduled task (rather than the Run key) lets the app start elevated
    # at sign-in without a UAC prompt. No time limit, runs on battery.
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts {APP_TITLE} when you sign in.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{xml_escape(user)}</UserId><Delay>PT10S</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{xml_escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{xml_escape(program)}</Command><Arguments>{xml_escape(args)}</Arguments></Exec>
  </Actions>
</Task>
"""


def set_startup(enabled: bool) -> tuple[bool, str]:
    if not enabled:
        r = _schtasks("/Delete", "/TN", APP_NAME, "/F")
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    program, args = launch_command()
    domain = os.environ.get("USERDOMAIN", "")
    user = f"{domain}\\{os.environ.get('USERNAME', '')}" if domain else os.environ.get("USERNAME", "")
    fd, xml_path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(build_task_xml(program, args, user))
        r = _schtasks("/Create", "/TN", APP_NAME, "/XML", xml_path, "/F")
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    finally:
        with contextlib.suppress(OSError):
            os.remove(xml_path)


# ---------------------------------------------------------------------------
# Tray icon image
# ---------------------------------------------------------------------------
def make_icon_image(state: str):
    from PIL import Image, ImageDraw, ImageFont

    colors = {"on": (118, 185, 0), "off": (110, 110, 110), "error": (200, 60, 50)}
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, size - 3, size - 3), radius=14, fill=colors[state])
    font = None
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        with contextlib.suppress(OSError):
            font = ImageFont.truetype(name, 42)
            break
    if font is None:
        try:
            font = ImageFont.load_default(size=42)
        except TypeError:
            font = ImageFont.load_default()
    text = "!" if state == "error" else "G"
    d.text((size / 2, size / 2 + 1), text, font=font, fill="white", anchor="mm")
    if state == "off":  # diagonal strike so on/off reads at a glance
        d.line((12, size - 12, size - 12, 12), fill="white", width=6)
    return img


# ---------------------------------------------------------------------------
# Tray application
# ---------------------------------------------------------------------------
class TrayApp:
    def __init__(self) -> None:
        import pystray

        self.pystray = pystray
        self.config = load_config()
        self.lock = threading.Lock()
        self.dialog_open = False
        self.hotkey_ok = False
        self.error: str | None = None
        self.mode: int | None = None
        self._startup_cached = False
        self.indicator = False
        self.controller: GSyncController | None = None
        try:
            self.controller = GSyncController()
            self.mode = self.controller.read_mode()
            self.indicator = self.controller.read_indicator()
        except NvApiError as e:
            self.error = str(e)

        self.hotkeys = HotkeyListener(self.on_hotkey)
        self.icon = pystray.Icon(APP_NAME, make_icon_image(self._icon_state()),
                                 self._tooltip(), menu=self._build_menu())

    # -- state text ---------------------------------------------------------
    def _icon_state(self) -> str:
        if self.error or self.mode is None:
            return "error"
        return "off" if self.mode == MODE_OFF else "on"

    def _status_text(self) -> str:
        if self.error:
            return "G-SYNC: unavailable"
        if self.mode == MODE_OFF:
            return "G-SYNC: OFF"
        return f"G-SYNC: ON ({MODE_NAMES.get(self.mode, '?')})"

    def _hotkey_text(self) -> str:
        hk = self.config["hotkey"]
        return format_hotkey(hk["modifiers"], hk["vk"])

    def _tooltip(self) -> str:
        return f"{self._status_text()}\nHotkey: {self._hotkey_text()}"[:127]

    def refresh_ui(self) -> None:
        self.icon.icon = make_icon_image(self._icon_state())
        self.icon.title = self._tooltip()
        self.icon.update_menu()

    def notify(self, message: str, force: bool = False) -> None:
        if force or self.config.get("notifications", True):
            with contextlib.suppress(Exception):
                self.icon.notify(message, APP_TITLE)

    # -- menu ---------------------------------------------------------------
    def _build_menu(self):
        Menu, Item = self.pystray.Menu, self.pystray.MenuItem
        enabled = lambda item: self.controller is not None  # noqa: E731

        def set_on_mode(mode):
            def handler(icon, item):
                self.config["on_mode"] = mode
                save_config(self.config)
                if self.mode not in (None, MODE_OFF):
                    self.apply_mode(mode)
                self.refresh_ui()
            return handler

        return Menu(
            Item(lambda item: self._status_text(), None, enabled=False),
            Item(lambda item: f"Turn G-SYNC {'on' if self.mode == MODE_OFF else 'off'}"
                 f"   ({self._hotkey_text()})",
                 lambda icon, item: self.toggle(), default=True, enabled=enabled),
            Item("When on, use", Menu(
                Item("Fullscreen only", set_on_mode(MODE_FULLSCREEN), radio=True,
                     checked=lambda item: self.config["on_mode"] == MODE_FULLSCREEN),
                Item("Fullscreen and windowed", set_on_mode(MODE_FULLSCREEN_WINDOWED), radio=True,
                     checked=lambda item: self.config["on_mode"] == MODE_FULLSCREEN_WINDOWED),
            ), enabled=enabled),
            Item("Show G-SYNC indicator", lambda icon, item: self.toggle_indicator(),
                 checked=lambda item: self.indicator, enabled=enabled),
            Menu.SEPARATOR,
            Item("Change hotkey...", lambda icon, item: self.open_hotkey_dialog()),
            Item("Show notifications", self._toggle_notifications,
                 checked=lambda item: self.config.get("notifications", True)),
            Item("Start with Windows", self._toggle_startup,
                 checked=lambda item: self._startup_cached),
            Item("Restart as administrator", self._restart_admin,
                 visible=lambda item: not is_admin()),
            Item("Refresh status", lambda icon, item: self.refresh_state()),
            Menu.SEPARATOR,
            Item("Exit", self.quit),
        )

    # -- actions ------------------------------------------------------------
    def refresh_state(self) -> None:
        if self.controller is None:
            return
        try:
            self.mode = self.controller.read_mode()
            self.indicator = self.controller.read_indicator()
            self.error = None
        except NvApiError as e:
            self.error = str(e)
        self.refresh_ui()

    def toggle_indicator(self) -> None:
        if self.controller is None:
            self.notify(self.error or "NVIDIA driver not available.", force=True)
            return
        try:
            with self.lock:
                target = not self.controller.read_indicator()
                self.controller.write_indicator(target)
                self.indicator = self.controller.read_indicator()
            if self.indicator == target:
                self.notify(f"G-SYNC indicator {'shown' if target else 'hidden'}. "
                            "Restart open games to see the change.")
            else:
                self.notify("The driver did not accept the change.", force=True)
        except NeedsAdminError:
            self.notify("Changing the indicator needs administrator rights. Use "
                        "\"Restart as administrator\" from the tray menu.", force=True)
        except NvApiError as e:
            self.notify(f"Couldn't change the indicator: {e}", force=True)
        self.refresh_ui()

    def apply_mode(self, target: int) -> None:
        if self.controller is None:
            self.notify(self.error or "NVIDIA driver not available.", force=True)
            return
        try:
            with self.lock:
                self.controller.write_mode(target)
                self.mode = self.controller.read_mode()
            self.error = None
            if self.mode == target:
                self.notify(self._status_text())
            else:
                self.notify("The driver did not accept the change.", force=True)
        except NeedsAdminError:
            self.notify("Changing G-SYNC needs administrator rights. Use "
                        "\"Restart as administrator\" from the tray menu.", force=True)
        except NvApiError as e:
            self.notify(f"Couldn't change G-SYNC: {e}", force=True)
        self.refresh_ui()

    def toggle(self) -> None:
        if self.controller is None:
            self.notify(self.error or "NVIDIA driver not available.", force=True)
            return
        try:
            current = self.controller.read_mode()
        except NvApiError as e:
            self.notify(f"Couldn't read G-SYNC state: {e}", force=True)
            return
        if current == MODE_OFF:
            target = self.config["on_mode"]
        else:
            if current != self.config["on_mode"]:  # remember the mode you were using
                self.config["on_mode"] = current
                save_config(self.config)
            target = MODE_OFF
        self.apply_mode(target)

    def on_hotkey(self) -> None:
        if not self.dialog_open:
            self.toggle()

    def _toggle_notifications(self, icon, item) -> None:
        self.config["notifications"] = not self.config.get("notifications", True)
        save_config(self.config)
        self.refresh_ui()

    def _toggle_startup(self, icon, item) -> None:
        ok, detail = set_startup(not self._startup_cached)
        self._startup_cached = startup_enabled()
        if not ok:
            self.notify(f"Couldn't update Start with Windows: {detail or 'access denied'}",
                        force=True)
        self.refresh_ui()

    def _restart_admin(self, icon, item) -> None:
        if relaunch_as_admin():  # the new copy waits for this one to exit
            self.quit(icon, item)

    def quit(self, icon=None, item=None) -> None:
        self.hotkeys.stop()
        self.icon.stop()

    # -- hotkey -------------------------------------------------------------
    def register_hotkey(self) -> bool:
        hk = self.config["hotkey"]
        self.hotkey_ok = self.hotkeys.register(hk["modifiers"], hk["vk"])
        return self.hotkey_ok

    def open_hotkey_dialog(self) -> None:
        if self.dialog_open:
            return
        self.dialog_open = True
        threading.Thread(target=self._hotkey_dialog, daemon=True).start()

    def _hotkey_dialog(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        user32 = ctypes.WinDLL("user32")
        # Free the current hotkey while capturing, so pressing it is recorded
        # instead of toggling G-SYNC.
        self.hotkeys.unregister()
        old = dict(self.config["hotkey"])
        captured: dict = {}
        saved = False

        root = tk.Tk()
        root.title(f"{APP_TITLE} - change hotkey")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        frm = ttk.Frame(root, padding=18)
        frm.grid()
        ttk.Label(frm, text="Press the new key combination for toggling G-SYNC.",
                  ).grid(column=0, row=0, columnspan=3, sticky="w")
        combo = tk.StringVar(value=format_hotkey(old["modifiers"], old["vk"]))
        ttk.Label(frm, textvariable=combo, font=("Segoe UI", 18, "bold"),
                  padding=(0, 14)).grid(column=0, row=1, columnspan=3)
        status = tk.StringVar(value="Current hotkey shown. Esc cancels.")
        ttk.Label(frm, textvariable=status, foreground="#666",
                  wraplength=360).grid(column=0, row=2, columnspan=3, sticky="w")

        def current_mods() -> int:
            down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)  # noqa: E731
            m = 0
            if down(VK_CONTROL):
                m |= MOD_CONTROL
            if down(VK_MENU):
                m |= MOD_ALT
            if down(VK_SHIFT):
                m |= MOD_SHIFT
            if down(VK_LWIN) or down(VK_RWIN):
                m |= MOD_WIN
            return m

        def on_key(event):
            vk = event.keycode  # On Windows, Tk's keycode is the virtual-key code
            mods = current_mods()
            if vk == VK_ESCAPE and not mods:
                close()
                return "break"
            if vk in MODIFIER_VKS:
                prefix = format_hotkey(mods, 0).rsplit("+", 1)[0] if mods else ""
                combo.set((prefix + "+ ...") if prefix else "...")
                return "break"
            ok, why = hotkey_is_valid(mods, vk)
            if not ok:
                status.set(why)
                return "break"
            captured.update(modifiers=mods, vk=vk)
            combo.set(format_hotkey(mods, vk))
            status.set("Click Save to use this hotkey.")
            save_btn.state(["!disabled"])
            return "break"

        def do_save():
            nonlocal saved
            if not captured:
                return
            if self.hotkeys.register(captured["modifiers"], captured["vk"]):
                self.config["hotkey"] = dict(captured)
                save_config(self.config)
                self.hotkey_ok = saved = True
                close()
            else:
                status.set("That combination is reserved by Windows or already used "
                           "by another app. Try a different one.")

        def reset_default():
            captured.update(DEFAULT_HOTKEY)
            combo.set(format_hotkey(DEFAULT_HOTKEY["modifiers"], DEFAULT_HOTKEY["vk"]))
            status.set("Click Save to use the default hotkey.")
            save_btn.state(["!disabled"])

        def close():
            root.destroy()

        btns = ttk.Frame(frm, padding=(0, 14, 0, 0))
        btns.grid(column=0, row=3, columnspan=3, sticky="e")
        ttk.Button(btns, text="Reset to default", command=reset_default,
                   takefocus=False).grid(column=0, row=0, padx=(0, 24))
        save_btn = ttk.Button(btns, text="Save", command=do_save, takefocus=False)
        save_btn.grid(column=1, row=0, padx=4)
        save_btn.state(["disabled"])
        ttk.Button(btns, text="Cancel", command=close, takefocus=False).grid(column=2, row=0)

        root.bind("<KeyPress>", on_key)
        root.protocol("WM_DELETE_WINDOW", close)
        root.after(50, root.focus_force)
        try:
            root.mainloop()
        finally:
            if not saved:  # restore the previous hotkey
                self.hotkey_ok = self.hotkeys.register(old["modifiers"], old["vk"])
            self.dialog_open = False
            self.refresh_ui()
            if saved:
                self.notify(f"Hotkey set to {self._hotkey_text()}", force=True)

    # -- run ----------------------------------------------------------------
    def run(self) -> None:
        self._startup_cached = startup_enabled()
        self.hotkeys.start()

        def setup(icon):
            icon.visible = True
            if not self.register_hotkey():
                self.notify(f"Hotkey {self._hotkey_text()} is already in use. "
                            "Pick another with \"Change hotkey...\".", force=True)
            if self.error:
                self.notify(self.error, force=True)
            else:
                self.notify(f"{self._status_text()}. Press {self._hotkey_text()} to toggle.")
            self.refresh_ui()

        self.icon.run(setup=setup)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_cli(args) -> int:
    def out(text: str) -> None:
        if sys.stdout:
            print(text)

    try:
        ctrl = GSyncController()
        if args.status:
            out(f"G-SYNC is {MODE_NAMES[ctrl.read_mode()]}")
            return 0
        cfg = load_config()
        on_mode = {"fullscreen": MODE_FULLSCREEN,
                   "windowed": MODE_FULLSCREEN_WINDOWED}.get(args.mode, cfg["on_mode"])
        current = ctrl.read_mode()
        if args.on:
            target = on_mode
        elif args.off:
            target = MODE_OFF
        else:
            target = on_mode if current == MODE_OFF else MODE_OFF
        ctrl.write_mode(target)
        out(f"G-SYNC is now {MODE_NAMES[ctrl.read_mode()]}")
        return 0
    except NeedsAdminError:
        out("Administrator rights are required. Run from an elevated prompt.")
        return 2
    except NvApiError as e:
        out(str(e))
        return 1


def main() -> int:
    p = argparse.ArgumentParser(prog=APP_NAME, description="Toggle NVIDIA G-SYNC.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--toggle", action="store_true", help="toggle G-SYNC and exit")
    g.add_argument("--on", action="store_true", help="turn G-SYNC on and exit")
    g.add_argument("--off", action="store_true", help="turn G-SYNC off and exit")
    g.add_argument("--status", action="store_true", help="print the current state and exit")
    p.add_argument("--mode", choices=("fullscreen", "windowed"),
                   help="mode to use when turning on (default: last used)")
    p.add_argument("--relaunched", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()

    if not IS_WINDOWS:
        print("SyncSwitch only runs on Windows.")
        return 1

    if args.toggle or args.on or args.off or args.status:
        return run_cli(args)

    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp dialog text
    mutex = acquire_single_instance(wait_seconds=10 if args.relaunched else 0)
    if mutex is None:
        return 0  # already running in the tray
    TrayApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
