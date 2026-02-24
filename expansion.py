"""Text expansion: Auto triggers (type abbreviation to expand). Paste via clipboard (rich text)."""
import threading
import time
import logging
import ctypes

import keyboard
from pynput.keyboard import Controller, Key

import clipboard_paste

BUFFER_SIZE = 300


class ExpansionEngine:
    """Handles Auto triggers (buffer match). Pastes rich text via clipboard."""

    def __init__(self, get_children_callback, get_settings_callback):
        """
        Args:
            get_children_callback: Callable() -> list of root folder/phrase items (data_model format).
            get_settings_callback: Callable() -> settings dict.
        """
        self._get_children = get_children_callback
        self._get_settings = get_settings_callback
        self._buffer = []
        self._lock = threading.Lock()
        self._sending = False
        self._controller = Controller()
        self._keyboard_hook = None

    # ──────────────────────────── helpers ────────────────────────────────

    def _char_from_event(self, event):
        name = getattr(event, "name", None)
        if not name or len(name) > 1:
            if name == "space":
                return " "
            return None
        return name

    def _is_phrase_dialog_active(self):
        """Disable expansions while Add/Edit phrase dialogs are focused."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return False
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
            title = (buf.value or "").strip().lower()
            return title in ("add phrase", "edit phrase")
        except Exception:
            return False

    def _get_auto_triggers(self):
        from data_model import collect_auto_triggers
        return collect_auto_triggers(self._get_children())

    def _execute_phrase(self, phrase_item):
        """Paste phrase's rich text (clipboard + Ctrl+V). Used by the auto-trigger path."""
        html = (phrase_item.get("expansion_html") or "").strip()
        if not html:
            return
        clipboard_paste.paste_rich_text(html)
        time.sleep(0.15)

    # ─────────────────────── keyboard hook ───────────────────────────────

    def _on_key_press(self, event):
        with self._lock:
            if self._sending:
                return
            if self._is_phrase_dialog_active():
                return

            char = self._char_from_event(event)
            if char is not None:
                self._buffer.append(char)
                if len(self._buffer) > BUFFER_SIZE:
                    self._buffer.pop(0)
                self._check_auto_expand()
            else:
                name = (getattr(event, "name", None) or "").lower()
                if name == "backspace":
                    if self._buffer:
                        self._buffer.pop()

    # ──────────────────────── auto-expand ────────────────────────────────

    def _check_auto_expand(self):
        """If buffer ends with an Auto trigger, remove trigger text and paste phrase."""
        triggers = self._get_auto_triggers()
        if not triggers:
            return
        buf_str = "".join(self._buffer)
        matched_trigger = None
        matched_phrase = None
        for trigger, phrase in sorted(triggers.items(), key=lambda x: -len(x[0])):
            if buf_str.endswith(trigger):
                matched_trigger = trigger
                matched_phrase = phrase
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
        self._keyboard_hook = keyboard.on_press(self._on_key_press)

    def stop(self):
        if self._keyboard_hook is not None:
            self._keyboard_hook()
            self._keyboard_hook = None
        with self._lock:
            self._buffer.clear()
