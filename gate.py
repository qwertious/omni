"""Decides whether Omni may use the machine right now.

Two questions: has the person stopped using the computer, and is there clearly
enough free memory to load a model without squeezing whatever else is running.
"""
import ctypes
import subprocess
import sys
import time

GB = 1024 ** 3
_WIN = sys.platform == "win32"


def idle_seconds():
    """Seconds since the last keyboard or mouse input on this desktop session."""
    if not _WIN:
        return 1e9

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    tick = ctypes.windll.kernel32.GetTickCount()
    return max(0.0, ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0)


def ram():
    """(total, free) system memory in bytes."""
    if not _WIN:
        return 0, 0

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullTotalPhys, m.ullAvailPhys


_vram = {"at": 0.0, "v": (0, 0)}


def vram(max_age=4):
    """(total, free) video memory in bytes, from nvidia-smi. (0, 0) if there is no NVIDIA card."""
    if time.time() - _vram["at"] < max_age:
        return _vram["v"]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()
        total, free = [int(x) * 1024 * 1024 for x in out[0].split(",")]
        _vram.update(at=time.time(), v=(total, free))
    except Exception:
        _vram.update(at=time.time(), v=(0, 0))
    return _vram["v"]


_gpu = {"name": None}


def gpu_name():
    if _gpu["name"] is None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=6,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            _gpu["name"] = out.strip().splitlines()[0] if out.strip() else ""
        except Exception:
            _gpu["name"] = ""
    return _gpu["name"]


def screen_state():
    """Why a full-screen window should not be put up right now, or '' if nothing is in the way.

    Covers a locked or switched-away session, a full-screen game or video, presentation
    mode, and any app that asked Windows to keep the display on (video players do).
    """
    if not _WIN:
        return "not on Windows"
    try:
        u32 = ctypes.windll.user32
        desk = u32.OpenInputDesktop(0, False, 0x0100)      # DESKTOP_SWITCHDESKTOP
        if not desk:
            return "the computer is locked"
        u32.CloseDesktop(desk)
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            if state.value == 1:
                return "the computer is locked or another user is signed in"
            if state.value in (2, 3):
                return "a full-screen app or game is open"
            if state.value == 4:
                return "presentation mode is on"
        flags = ctypes.c_ulong(0)
        if ctypes.windll.powrprof.CallNtPowerInformation(16, None, 0, ctypes.byref(flags), 4) == 0:
            if flags.value & 0x2:                            # ES_DISPLAY_REQUIRED
                return "an app is keeping the display on (a video, perhaps)"
    except Exception:
        return ""
    return ""


def snapshot():
    rt, rf = ram()
    vt, vf = vram()
    return {"idle": idle_seconds(), "ram_total": rt, "ram_free": rf,
            "vram_total": vt, "vram_free": vf}


def memory_ok(model_bytes, already_loaded, reclaimable, settings):
    """Can a model of this size be loaded without crowding the machine?

    `reclaimable` is video memory held by other models Omni itself loaded; Ollama
    frees those when it swaps. Returns (ok, reason).
    """
    if already_loaded or not model_bytes:
        return True, ""
    rt, rf = ram()
    vt, vf = vram(max_age=0)
    reserve = float(settings.get("ram_reserve_gb", 6)) * GB
    headroom = float(settings.get("vram_headroom_gb", 1.5)) * GB
    need = model_bytes + headroom
    if vt == 0:  # no dedicated card: everything lands in system memory
        if rf - need >= reserve:
            return True, ""
        return False, "needs %.0f GB of memory with %.0f GB to spare; %.1f GB is free" % (
            need / GB, reserve / GB, rf / GB)
    avail = vf + reclaimable
    # Whatever does not fit on the card spills into system memory. That is fine as long as
    # the card is not mostly taken by something else and plenty of system memory stays free.
    spill = max(0.0, need - avail)
    if avail < min(need, 0.7 * vt):
        return False, "needs about %.0f GB of video memory; %.1f GB is free" % (
            min(need, 0.7 * vt) / GB, avail / GB)
    floor = reserve if spill > 0.5 * GB else 2 * GB
    if rf - spill < floor:
        return False, "needs %.0f GB of system memory free; %.1f GB is free" % (
            (spill + floor) / GB, rf / GB)
    return True, ""
