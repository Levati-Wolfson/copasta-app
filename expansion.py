"""Text expansion: Auto (type trigger) and Hotkey. Paste via clipboard (rich text)."""
import threading
import time
import logging
import ctypes

import keyboard
from pynput.keyboard import Controller, Key

import clipboard_paste

BUFFER_SIZE = 300


class ExpansionEngine:
    """Handles Auto triggers (buffer match) and Hotkey triggers. Pastes rich text via clipboard."""

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
        self._hotkey_removers = []

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

    def _get_hotkey_phrases(self):
        from data_model import collect_hotkey_phrases
        return collect_hotkey_phrases(self._get_children())

    def _get_expansion_hotkey(self):
        settings = self._get_settings() or {}
        return (settings.get("expansion_hotkey") or "ctrl+alt+e").strip()

    def _execute_phrase(self, phrase_item):
        """Paste phrase's rich text (clipboard + Ctrl+V)."""
        html = (phrase_item.get("expansion_html") or "").strip()
        if not html:
            return
        with self._lock:
            self._sending = True
        clipboard_paste.paste_rich_text(html)
        time.sleep(0.15)
        with self._lock:
            self._sending = False

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
                return

            if getattr(event, "name", None) == "backspace":
                if self._buffer:
                    self._buffer.pop()

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
            # Send backspaces to remove the typed trigger
            for _ in range(n):
                self._controller.press(Key.backspace)
                self._controller.release(Key.backspace)
            time.sleep(0.02)
            self._execute_phrase(matched_phrase)

        threading.Thread(target=do_replace, daemon=True).start()

    def _check_hotkey_expand(self):
        """
        Expand phrase in Hotkey mode if current typed buffer ends with its abbreviation.
        Triggered by a single global expansion hotkey.
        """
        with self._lock:
            if self._sending:
                return
            if self._is_phrase_dialog_active():
                return
            phrases = self._get_hotkey_phrases()
            if not phrases:
                return
            buf_str = "".join(self._buffer)
            matched_trigger = None
            matched_phrase = None
            for phrase in sorted(phrases, key=lambda p: -len((p.get("trigger") or "").strip())):
                trig = (phrase.get("trigger") or "").strip()
                if trig and buf_str.endswith(trig):
                    matched_trigger = trig
                    matched_phrase = phrase
                    break
            if not matched_trigger or not matched_phrase:
                return

            n = len(matched_trigger)
            if n > 0:
                del self._buffer[-n:]

        def do_replace():
            time.sleep(0.02)
            for _ in range(n):
                self._controller.press(Key.backspace)
                self._controller.release(Key.backspace)
            time.sleep(0.02)
            self._execute_phrase(matched_phrase)

        threading.Thread(target=do_replace, daemon=True).start()

    def _reregister_hotkeys(self):
        for remove in self._hotkey_removers:
            try:
                remove()
            except Exception:
                logging.exception("Failed removing existing phrase hotkey registration.")
        self._hotkey_removers.clear()
        hotkey = self._get_expansion_hotkey()
        if not hotkey:
            return
        try:
            remove = keyboard.add_hotkey(hotkey, self._check_hotkey_expand)
            self._hotkey_removers.append(remove)
        except Exception:
            logging.exception("Failed registering global expansion hotkey: %s", hotkey)

    def start(self):
        self._keyboard_hook = keyboard.on_press(self._on_key_press)
        self._reregister_hotkeys()

    def stop(self):
        if self._keyboard_hook is not None:
            self._keyboard_hook()
            self._keyboard_hook = None
        for remove in self._hotkey_removers:
            try:
                remove()
            except Exception:
                logging.exception("Failed removing hotkey during engine stop.")
        self._hotkey_removers.clear()
        with self._lock:
            self._buffer.clear()

    def refresh_hotkeys(self):
        """Call after data change to re-register hotkeys."""
        self._reregister_hotkeys()
