"""Text expansion: Auto triggers (type abbreviation to expand). Paste via clipboard (rich text)."""
import threading
import time
import logging
import ctypes

from pynput.keyboard import Controller, Key

import clipboard_paste

BUFFER_SIZE = 300

_user32            = ctypes.windll.user32
_GetAsyncKeyState  = _user32.GetAsyncKeyState
_GetKeyState       = _user32.GetKeyState
_MapVirtualKeyW    = _user32.MapVirtualKeyW
_ToUnicode         = _user32.ToUnicode
_ToUnicode.restype = ctypes.c_int

_VK_BACKSPACE = 0x08
_VK_SHIFT     = 0x10
_VK_CAPITAL   = 0x14   # Caps Lock

# Blocking modifier VK codes: Ctrl, Alt, Win (left + right).
# Shift is intentionally excluded — abbreviations may use uppercase letters.
_MODIFIER_VKS = (0x11, 0x12, 0x5B, 0x5C)

# VK codes to poll each cycle.
#   0x08        backspace
#   0x20        space
#   0x30–0x39   digit row  (0-9; with Shift produces !@#$%^&*() etc.)
#   0x41–0x5A   letters    (A-Z)
#   0xBA–0xC0   OEM_1 … OEM_3 + OEM_PLUS/MINUS/PERIOD/COMMA/2
#                 (covers ; : ' " [ ] - _ = + , . / on US; å ä ö etc. on Swedish)
#   0xDB–0xDF   OEM_4 … OEM_8  ([ \ ] ' on US; further layout-specific chars)
#   0xE2        OEM_102 — extra key present on European/Swedish keyboards
_VK_POLL = (
    _VK_BACKSPACE,
    0x20,
    *range(0x30, 0x3A),
    *range(0x41, 0x5B),
    *range(0xBA, 0xC1),
    *range(0xDB, 0xE0),
    0xE2,
)

_KB_STATE = ctypes.c_ubyte * 256


def _modifier_held():
    """Return True if Ctrl, Alt, or Win is currently pressed (physical or synthetic)."""
    return any(_GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS)


_VK_SPACE_SCAN = None   # lazily filled in _build_dead_key_vks / _vk_to_char


def _flush_dead_key(buf):
    """
    Consume any dead-key state accumulated in this thread by calling ToUnicode
    with Space and an empty key-state.  Dead-key + Space always resolves to a
    single printable character on every layout, guaranteeing the state is
    cleared after exactly one extra call.
    """
    global _VK_SPACE_SCAN
    if _VK_SPACE_SCAN is None:
        _VK_SPACE_SCAN = _MapVirtualKeyW(0x20, 0)
    empty = _KB_STATE()
    _ToUnicode(0x20, _VK_SPACE_SCAN, empty, buf, 4, 0)


def _vk_to_char(vk):
    """
    Translate a VK code to its Unicode character using the current keyboard
    layout, honouring Shift and Caps Lock.  Returns None for non-printable
    results.

    wFlags=0x04 makes ToUnicode a pure "peek": it returns what the key would
    produce (including dead-key compositions such as dead-circumflex+Space →
    '^') WITHOUT consuming or modifying any dead-key state in the system.
    This means even if the poll loop missed a dead-key VK press (too fast for
    the 1 ms poll cycle), the subsequent call for Space returns the composed
    character while leaving the foreground app's dead-key state untouched.
    """
    state = _KB_STATE()
    if _GetAsyncKeyState(_VK_SHIFT) & 0x8000:
        state[_VK_SHIFT] = 0x80
    if _GetKeyState(_VK_CAPITAL) & 0x01:       # toggle bit = Caps Lock on
        state[_VK_CAPITAL] = 0x01
    scan = _MapVirtualKeyW(vk, 0)              # MAPVK_VK_TO_VSC
    buf  = ctypes.create_unicode_buffer(4)
    n    = _ToUnicode(vk, scan, state, buf, 4, 0x04)   # 0x04 = peek, no state change
    if n == 1 and buf[0] and buf[0].isprintable():
        return buf[0]
    if n == -1:
        # Safety net: dead-key VK not caught by _dead_key_vks at startup.
        # With wFlags=0x04 no state was modified, so no flush is needed —
        # just log so we can extend the table if this appears.
        logging.warning(
            "_vk_to_char safety-net: VK=0x%02X produced dead-key (n=-1) "
            "but was not in dead_key_vks",
            vk,
        )
    return None


def _build_dead_key_vks():
    """
    Return a frozenset of VK codes that produce a dead key under any modifier
    combination on the current keyboard layout.

    Keying on the VK alone (rather than a (vk, shift) pair) ensures we always
    skip those VKs in the poll loop regardless of the exact Shift state at the
    moment of detection — eliminating the timing window where shift_held could
    be sampled a fraction too late.

    The Space-key flush is used after every dead-key probe because it is the
    only universally reliable way to clear the dead-key state: pressing the
    same dead key again can itself produce another dead-key result on some
    layouts, leaving residual state that corrupts subsequent probes.
    """
    dead_vks = set()
    buf = ctypes.create_unicode_buffer(4)
    for vk in _VK_POLL:
        if vk in (_VK_BACKSPACE, 0x20):
            continue
        scan = _MapVirtualKeyW(vk, 0)
        for shift_held in (False, True):
            state = _KB_STATE()
            if shift_held:
                state[_VK_SHIFT] = 0x80
            n = _ToUnicode(vk, scan, state, buf, 4, 0)
            if n == -1:
                dead_vks.add(vk)
                _flush_dead_key(buf)   # Space flush — always clears state cleanly
    logging.info(
        "dead-key VKs detected at startup: %s",
        ", ".join(f"0x{v:02X}" for v in sorted(dead_vks)) or "(none)",
    )
    return frozenset(dead_vks)


class ExpansionEngine:
    """Handles Auto triggers (buffer match). Pastes rich text via clipboard."""

    def __init__(self, get_children_callback, get_settings_callback):
        """
        Args:
            get_children_callback: Callable() -> list of root folder/phrase items.
            get_settings_callback: Callable() -> settings dict.
        """
        self._get_children    = get_children_callback
        self._get_settings    = get_settings_callback
        self._buffer          = []
        self._lock            = threading.Lock()
        self._sending         = False
        self._controller      = Controller()
        self._stop_event      = threading.Event()
        self._poll_thread     = None
        # Pre-built set of VK codes that can produce dead keys on this layout.
        # The poll loop skips ToUnicode for any of these VKs regardless of the
        # Shift state.  For any dead-key that the poll misses (pressed and
        # released within one 1 ms cycle), _vk_to_char's wFlags=0x04 peek mode
        # ensures no dead-key state is consumed from the system, so the
        # foreground app's composition always works correctly.
        self._dead_key_vks = _build_dead_key_vks()

    # ──────────────────────────── helpers ────────────────────────────────

    def _is_phrase_dialog_active(self):
        """Return True when an Add/Edit Phrase dialog is in the foreground."""
        try:
            hwnd = _user32.GetForegroundWindow()
            if not hwnd:
                return False
            buf = ctypes.create_unicode_buffer(512)
            _user32.GetWindowTextW(hwnd, buf, 512)
            title = (buf.value or "").strip().lower()
            return title in ("add phrase", "edit phrase")
        except Exception:
            return False

    def _get_auto_triggers(self):
        from data_model import collect_auto_triggers
        return collect_auto_triggers(self._get_children())

    def _execute_phrase(self, phrase_item):
        """Paste phrase rich text via clipboard + Ctrl+V."""
        html = (phrase_item.get("expansion_html") or "").strip()
        if not html:
            return
        clipboard_paste.paste_rich_text(html)
        time.sleep(0.15)

    # ─────────────────────── polling loop ────────────────────────────────

    def _poll_loop(self):
        """
        Detect key presses by polling GetAsyncKeyState every ~1 ms.

        Why polling instead of a WH_KEYBOARD_LL hook:
        A low-level keyboard hook is called synchronously before the key event
        is delivered to any application.  Even a fast Python callback adds a few
        milliseconds of latency (GIL acquisition + Python overhead).  For
        keyboard shortcuts such as Ctrl+Tab that delay is invisible because the
        user naturally pauses between keys.  For Ctrl+scroll-to-zoom the mouse
        wheel fires concurrently on a separate channel; if Ctrl's delivery is
        delayed even briefly, the first scroll events arrive without MK_CONTROL
        and the app scrolls instead of zooms.  Polling with GetAsyncKeyState adds
        zero latency to keyboard event delivery, so Ctrl+scroll works normally.
        """
        # Force Windows to create a message queue for this thread.
        #
        # ToUnicode stores dead-key state in the calling thread's input queue.
        # A thread that has never called any messaging function has no queue;
        # in that case Windows may fall back to the foreground thread's queue,
        # meaning our ToUnicode calls would corrupt the foreground app's own
        # dead-key composition state.  One PeekMessageW call is enough to
        # materialise a queue and guarantee full isolation from that point on.
        _msg_buf = (ctypes.c_byte * 48)()
        _user32.PeekMessageW(_msg_buf, None, 0, 0, 0x0000)   # PM_NOREMOVE

        prev_down: dict[int, bool] = {}

        while not self._stop_event.is_set():

            # If any blocking modifier is held the user is doing a shortcut —
            # clear the buffer and wait without processing further.
            if _modifier_held():
                with self._lock:
                    self._buffer.clear()
                prev_down = {}
                time.sleep(0.001)
                continue

            for vk in _VK_POLL:
                is_down  = bool(_GetAsyncKeyState(vk) & 0x8000)
                was_down = prev_down.get(vk, False)

                if is_down and not was_down:
                    # Key transitioned from up → down this cycle.
                    with self._lock:
                        if not self._sending:
                            if vk == _VK_BACKSPACE:
                                if self._buffer:
                                    self._buffer.pop()
                            else:
                                if vk in self._dead_key_vks:
                                    # Dead-key VK: skip ToUnicode for it entirely.
                                    # If the poll catches it, we avoid the call.
                                    # If the poll misses it (sub-1ms press),
                                    # _vk_to_char's wFlags=0x04 peek mode handles
                                    # the composition key safely without consuming
                                    # the system's dead-key state.
                                    logging.debug(
                                        "dead-key skip: VK=0x%02X (shift=%s)",
                                        vk,
                                        bool(_GetAsyncKeyState(_VK_SHIFT) & 0x8000),
                                    )
                                else:
                                    char = _vk_to_char(vk)
                                    logging.debug(
                                        "key VK=0x%02X → %r  (shift=%s)",
                                        vk, char,
                                        bool(_GetAsyncKeyState(_VK_SHIFT) & 0x8000),
                                    )
                                    if char and not self._is_phrase_dialog_active():
                                        self._buffer.append(char)
                                        if len(self._buffer) > BUFFER_SIZE:
                                            self._buffer.pop(0)
                                        self._check_auto_expand()

                prev_down[vk] = is_down

            time.sleep(0.001)

    # ──────────────────────── auto-expand ────────────────────────────────

    def _check_auto_expand(self):
        """If the buffer ends with a known trigger, erase it and paste the phrase."""
        triggers = self._get_auto_triggers()
        if not triggers:
            return
        buf_str = "".join(self._buffer)
        logging.debug("auto_expand: buf=%r  triggers=%r", buf_str[-30:], sorted(triggers.keys()))
        matched_trigger = matched_phrase = None
        for trigger, phrase in sorted(triggers.items(), key=lambda x: -len(x[0])):
            if buf_str.endswith(trigger):
                matched_trigger = trigger
                matched_phrase  = phrase
                break
        if not matched_trigger:
            return

        n = len(matched_trigger)
        del self._buffer[-n:]

        def do_replace():
            time.sleep(0.02)
            try:
                with self._lock:
                    self._sending = True
                for _ in range(n):
                    self._controller.press(Key.backspace)
                    self._controller.release(Key.backspace)
                    time.sleep(0.012)
                time.sleep(0.02)
                self._execute_phrase(matched_phrase)
            finally:
                with self._lock:
                    self._sending = False

        threading.Thread(target=do_replace, daemon=True).start()

    # ─────────────────────── lifecycle ───────────────────────────────────

    def start(self):
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="expansion-poll"
        )
        self._poll_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=0.5)
            self._poll_thread = None
        with self._lock:
            self._buffer.clear()
