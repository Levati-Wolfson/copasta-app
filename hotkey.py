"""
Global hotkey: suppressed via RegisterHotKey (main thread), detected via
GetAsyncKeyState polling (background thread).

Why this hybrid?
  RegisterHotKey consumes the key event so other apps never see it.
  GetAsyncKeyState queries raw hardware key state and sees the keys as pressed
  even when the event has been consumed — so polling still works for detection.
  A background-thread GetMessageW loop turned out to be unreliable alongside
  Tkinter's own main-thread message loop, so polling is used for detection
  instead.
"""
import ctypes
import threading
import time
import logging

_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_GetAsyncKeyState = _user32.GetAsyncKeyState

# RegisterHotKey modifier flags
_MOD_ALT      = 0x0001
_MOD_CONTROL  = 0x0002
_MOD_SHIFT    = 0x0004
_MOD_WIN      = 0x0008
_MOD_NOREPEAT = 0x4000   # fire once per press, not continuously while held

_HOTKEY_ID = 1   # arbitrary; one registration per thread is all we need

# Modifier name → RegisterHotKey flag
_MOD_NAMES = {
    "ctrl":    _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "alt":     _MOD_ALT,
    "shift":   _MOD_SHIFT,
    "win":     _MOD_WIN,
    "windows": _MOD_WIN,
}
# Modifier name → VK code tuple (for GetAsyncKeyState polling)
_MOD_VKS = {
    "ctrl":    (0x11,),
    "control": (0x11,),
    "alt":     (0x12,),
    "shift":   (0x10,),
    "win":     (0x5B, 0x5C),
    "windows": (0x5B, 0x5C),
}
_KEY_VKS = {
    "space":     0x20, "enter":  0x0D, "return": 0x0D,
    "tab":       0x09, "esc":    0x1B, "escape": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home":      0x24, "end":    0x23,
    "up":        0x26, "down":   0x28, "left":   0x25, "right": 0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}


def _parse_hotkey(hotkey_str):
    """
    Parse e.g. 'ctrl+shift+space' into:
      poll_groups  – list of VK-code tuples (one per key, for polling)
      reg_params   – (fsModifiers, vk) for RegisterHotKey, or None on failure
    """
    poll_groups = []
    mods = 0
    vk   = None

    for part in (p.strip().lower() for p in hotkey_str.split("+")):
        if part in _MOD_NAMES:
            mods |= _MOD_NAMES[part]
            poll_groups.append(_MOD_VKS[part])
        elif part in _KEY_VKS:
            vk = _KEY_VKS[part]
            poll_groups.append((vk,))
        elif len(part) == 1:
            vk = ord(part.upper())
            poll_groups.append((vk,))
        else:
            logging.warning("HotkeyPoller: unknown token %r in %r", part, hotkey_str)
            return poll_groups, None

    if vk is None:
        logging.warning("HotkeyPoller: no non-modifier key in %r", hotkey_str)
        return poll_groups, None

    return poll_groups, (mods | _MOD_NOREPEAT, vk)


class HotkeyPoller:
    """
    Detects and suppresses a configurable global hotkey.

    Must be created and stopped from the same thread (the Tkinter main thread).
    RegisterHotKey is called on that thread so WM_HOTKEY suppression is tied to
    it.  Detection uses GetAsyncKeyState polling in a background thread, which
    is unaffected by message-routing quirks.
    """

    def __init__(self, hotkey_str, callback, interval_ms=50):
        self._callback   = callback
        self._interval   = interval_ms / 1000.0
        self._was_active = False
        self._stop_event = threading.Event()
        self._registered = False

        poll_groups, reg_params = _parse_hotkey(hotkey_str)
        self._groups = poll_groups

        # Register from the calling (main) thread so suppression works correctly.
        if reg_params:
            mods, vk_code = reg_params
            logging.info(
                "HotkeyPoller: registering mods=0x%04X vk=0x%02X", mods, vk_code
            )
            if _user32.RegisterHotKey(None, _HOTKEY_ID, mods, vk_code):
                self._registered = True
                logging.info("HotkeyPoller: RegisterHotKey succeeded — hotkey is suppressed.")
            else:
                err = _kernel32.GetLastError()
                logging.warning(
                    "HotkeyPoller: RegisterHotKey failed (err=%d) — "
                    "hotkey works but won't be suppressed.", err
                )

        self._thread = threading.Thread(
            target=self._poll, daemon=True, name="hotkey-poll"
        )
        self._thread.start()

    def _poll(self):
        while not self._stop_event.is_set():
            active = bool(self._groups) and all(
                any(_GetAsyncKeyState(vk) & 0x8000 for vk in group)
                for group in self._groups
            )
            if active and not self._was_active:
                try:
                    self._callback()
                except Exception:
                    logging.exception("HotkeyPoller: callback error.")
            self._was_active = active
            time.sleep(self._interval)

    def stop(self):
        """Call from the same thread that created this instance (main thread)."""
        self._stop_event.set()
        if self._registered:
            _user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registered = False
            logging.info("HotkeyPoller: UnregisterHotKey called.")
        if self._thread is not None:
            self._thread.join(timeout=1.0)
