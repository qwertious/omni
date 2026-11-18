"""The away-mode screensaver, and the step-aside hotkey.

When the person has been away for a while and the makers are working, Omni opens its own
full-screen window (Edge or Chrome in kiosk mode, with a profile of its own) showing what is
being made. The moment there is keyboard or mouse input again, Omni closes it.

It stays away when the computer is locked, when a full-screen game, video or presentation is
up, and when some app has asked Windows to keep the display on.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time

import checker
import gate
import store

_WIN = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Saver(threading.Thread):
    daemon = True

    def __init__(self, worker, url):
        super().__init__(name="omni-saver")
        self.worker = worker
        self.url = url
        self.proc = None
        self.opened_at = 0.0
        self.preview = False
        self.reason = ""
        self._last_idle = 0.0
        self._lock = threading.Lock()

    # -- what the interface sees --------------------------------------------

    def status(self):
        st = self.worker.settings()
        if self.proc:
            return {"state": "showing", "reason": ""}
        if st.get("screensaver") != "on":
            return {"state": "off", "reason": ""}
        return {"state": "held back" if self.reason else "ready", "reason": self.reason,
                "after": st.get("saver_minutes", 6)}

    # -- opening and closing -------------------------------------------------

    def _browser(self):
        exe = checker.browser_path()
        if not exe:
            return None
        profile = os.path.join(store.OMNI_HOME, "saver-profile")
        return [exe, "--kiosk", self.url, "--edge-kiosk-type=fullscreen", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                "--disable-features=Translate,msEdgeSidebarV2,msImplicitSignin",
                "--hide-crash-restore-bubble", "--user-data-dir=" + profile]

    def show(self, preview=False):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return True
            cmd = self._browser()
            if not cmd:
                self.reason = "no Edge or Chrome to show it with"
                return False
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                self.reason = "could not start the browser (%s)" % e
                return False
            self.opened_at = time.time()
            self.preview = preview
            self._last_idle = 0.0
            self.reason = ""
            threading.Thread(target=self._bring_forward, args=(self.proc,), daemon=True).start()
            return True

    def _bring_forward(self, proc):
        """Windows does not let a program in the background put its window in front of the
        one you were using, so the kiosk window would open behind it. Once it appears, pin it
        on top of everything and hand it the keyboard."""
        if not _WIN:
            return
        hwnd = 0
        for _ in range(60):                      # the window takes a moment to appear
            time.sleep(0.15)
            if proc.poll() is not None:
                return
            hwnd = _window_of(proc.pid)
            if hwnd:
                break
        if not hwnd:
            return
        time.sleep(0.4)                          # let it go full screen first
        _force_front(hwnd)
        time.sleep(1.0)                          # Edge sometimes re-orders itself once loaded
        if self.proc is proc and proc.poll() is None:
            _force_front(hwnd)

    def hide(self):
        with self._lock:
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                           creationflags=NO_WINDOW)

    # -- deciding ---------------------------------------------------------------

    def _wanted(self, st):
        w = self.worker
        if w.held or w.aside or st.get("autonomy") == "off":
            return False
        return bool(w.job) or w.gate_state.get("state") in ("working", "resting", "waiting")

    def run(self):
        while True:
            time.sleep(0.4)
            try:
                self._step()
            except Exception as e:      # never let the saver take Omni down
                self.reason = "error: %s" % e

    def _step(self):
        st = self.worker.settings()
        idle = gate.idle_seconds()
        if self.proc:
            if self.proc.poll() is not None:          # closed by hand (Alt+F4)
                self.proc = None
                return
            settle = 2.5 if self.preview else 1.0     # the click that opened it is input too
            if time.time() - self.opened_at > settle and idle + 0.3 < self._last_idle:
                self.hide()
            elif not self.preview and (st.get("screensaver") != "on" or not self._wanted(st)):
                self.hide()
            self._last_idle = idle
            return
        if st.get("screensaver") != "on" or not self._wanted(st):
            self.reason = ""
            return
        if idle < float(st.get("saver_minutes", 6)) * 60:
            self.reason = ""
            return
        why = gate.screen_state()
        self.reason = why
        if not why:
            self.show()


# --- windows --------------------------------------------------------------------

def _window_of(pid):
    """The biggest visible top-level window belonging to process `pid`, or 0."""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append(((r.right - r.left) * (r.bottom - r.top), hwnd))
        return True

    u32.EnumWindows(each, 0)
    return max(found)[1] if found else 0


def _force_front(hwnd):
    """Topmost, shown, and (if Windows allows it) the foreground window."""
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    HWND_TOPMOST = wintypes.HWND(-1)
    u32.ShowWindow(hwnd, 5)                                      # SW_SHOW
    u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # NOSIZE|NOMOVE|SHOW
    fg = u32.GetForegroundWindow()
    fg_thread = u32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = k32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and u32.AttachThreadInput(me, fg_thread, True))
    try:
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
        u32.SetActiveWindow(hwnd)
    finally:
        if attached:
            u32.AttachThreadInput(me, fg_thread, False)
    return u32.GetForegroundWindow() == hwnd


# --- hotkey ---------------------------------------------------------------------

MODS = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
NAMED = {"pause": 0x13, "scrolllock": 0x91, "end": 0x23, "home": 0x24, "insert": 0x2D, "space": 0x20,
         "pageup": 0x21, "pagedown": 0x22, "backspace": 0x08, "delete": 0x2E}


def parse(text):
    """'ctrl+alt+shift+o' -> (modifiers, virtual key), or None if it is not a usable hotkey."""
    parts = [p.strip().lower() for p in (text or "").replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in MODS:
            return None
        mods |= MODS[p]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key in NAMED:
        vk = NAMED[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        return None
    if not mods and not (vk in (0x13, 0x91) or vk >= 0x7C):   # bare keys only for Pause and F13+
        return None
    return mods, vk


class Hotkey(threading.Thread):
    """One global hotkey that makes Omni step aside."""
    daemon = True

    def __init__(self, on_press):
        super().__init__(name="omni-hotkey")
        self.on_press = on_press
        self.tid = 0
        self.ok = False
        self.keys = ""
        self.error = ""
        self.parse = parse

    def status(self):
        return {"ok": self.ok, "keys": self.keys, "error": self.error}

    def reload(self):
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, 0x8001, 0, 0)

    def _register(self):
        u32 = ctypes.windll.user32
        u32.UnregisterHotKey(None, 1)
        self.keys = store.get_setting("hotkey") or ""
        got = parse(self.keys)
        if not got:
            self.ok, self.error = False, "not a hotkey Omni understands"
            return
        self.ok = bool(u32.RegisterHotKey(None, 1, got[0] | 0x4000, got[1]))   # MOD_NOREPEAT
        self.error = "" if self.ok else "another program already uses %s" % self.keys

    def run(self):
        if not _WIN:
            self.error = "only on Windows"
            return
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register()
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:              # WM_HOTKEY
                try:
                    u32.MessageBeep(0x40)
                    self.on_press()
                except Exception as e:
                    self.error = str(e)
            elif msg.message == 0x8001:            # our "settings changed"
                self._register()
