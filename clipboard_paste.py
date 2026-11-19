"""Rich text paste: save clipboard, set HTML + plain text, Ctrl+V, restore. Uses Windows CF_HTML."""
import time
import threading
import logging
import ctypes
from html.parser import HTMLParser

import win32clipboard
from pynput.keyboard import Controller, Key

from phrase_images import PhraseImage, strip_preview_sizes

CF_HTML = None

_user32 = ctypes.windll.user32
_VK_LSHIFT = 0xA0
_VK_RSHIFT = 0xA1


def _physical_shift_down():
    """True if either Shift key is currently held (GetAsyncKeyState)."""
    return bool(
        (_user32.GetAsyncKeyState(_VK_LSHIFT) & 0x8000)
        or (_user32.GetAsyncKeyState(_VK_RSHIFT) & 0x8000)
    )


def _ensure_shift_released_before_ctrl_v():
    """
    Triggers that end with Shift (capital letters, !, etc.) often leave Shift
    down briefly. Many apps map Ctrl+Shift+V to 'paste without formatting',
    so a plain Ctrl+V paste can lose formatting.
    Wait for Shift to go up, then synthesize Shift release if still down.
    """
    deadline = time.perf_counter() + 0.5
    while _physical_shift_down() and time.perf_counter() < deadline:
        time.sleep(0.006)
    if not _physical_shift_down():
        return
    ctrl = Controller()
    try:
        # Key.shift is left Shift (0xA0); Key.shift_r is right (0xA1).
        ctrl.release(Key.shift)
        ctrl.release(Key.shift_r)
    except Exception:
        logging.debug("paste: synthetic Shift release failed", exc_info=True)
    time.sleep(0.02)


def _get_cf_html():
    global CF_HTML
    if CF_HTML is None:
        CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")
    return CF_HTML


def _build_cf_html_content(html_fragment):
    """Build CF_HTML bytes with correct byte offsets."""
    body = (
        "<html><head><meta charset='utf-8'></head>"
        "<body><!--StartFragment-->%s<!--EndFragment--></body></html>"
    ) % strip_preview_sizes(html_fragment or "")
    header_tpl = (
        "Version:0.9\r\nStartHTML:%09d\r\nEndHTML:%09d\r\n"
        "StartFragment:%09d\r\nEndFragment:%09d\r\n\r\n"
    )
    body_bytes = body.encode("utf-8")
    start_marker = b"<!--StartFragment-->"
    end_marker = b"<!--EndFragment-->"
    header_placeholder = header_tpl % (0, 0, 0, 0)
    start_html = len(header_placeholder.encode("ascii"))
    end_html = start_html + len(body_bytes)
    start_frag = start_html + body_bytes.index(start_marker) + len(start_marker)
    end_frag = start_html + body_bytes.index(end_marker)
    header = header_tpl % (start_html, end_html, start_frag, end_frag)
    return header.encode("ascii") + body_bytes


def _open_clipboard():
    for _ in range(50):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(0.02)
    return False


class _PlainTextParser(HTMLParser):
    """Extract visible text and line breaks from a phrase's HTML."""

    _BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "blockquote", "pre",
                   "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.image_sources = []
        self._block_break_pending = False
        self._ignored_tag = None

    def _append(self, text):
        if self._block_break_pending:
            if self.parts and not self.parts[-1].endswith("\n"):
                self.parts.append("\n")
            self._block_break_pending = False
        self.parts.append(text)

    def handle_starttag(self, tag, attrs):
        if self._ignored_tag:
            return
        if tag in ("script", "style"):
            self._ignored_tag = tag
        elif tag == "br":
            self._append("\n")
        elif tag == "img":
            self.image_sources.append(dict(attrs).get("src") or "")
        elif tag in self._BLOCK_TAGS:
            self._block_break_pending = True

    def handle_endtag(self, tag):
        if self._ignored_tag:
            if tag == self._ignored_tag:
                self._ignored_tag = None
        elif tag in self._BLOCK_TAGS:
            self._block_break_pending = True

    def handle_data(self, text):
        if self._ignored_tag or not text:
            return
        if self._block_break_pending and not text.strip(" \t\r\n"):
            return  # Ignore indentation between HTML blocks.
        self._append(text.replace("\r\n", "\n").replace("\r", "\n"))


def _parse_phrase_html(html):
    parser = _PlainTextParser()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts), parser.image_sources


def html_to_plain(html):
    """Return Unicode text with entities decoded once and line breaks intact."""
    text, _ = _parse_phrase_html(html)
    return text


def _write_open_clipboard(html_fragment):
    text, images = _parse_phrase_html(html_fragment)
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text.replace("\n", "\r\n"), win32clipboard.CF_UNICODETEXT)
    try:
        win32clipboard.SetClipboardData(_get_cf_html(), _build_cf_html_content(html_fragment))
    except Exception:
        logging.exception("Failed setting clipboard HTML format.")
    # Offering a standalone bitmap for a mixed phrase could cause an editor to
    # pick that bitmap and drop the surrounding text. Use HTML for mixed phrases.
    if len(images) == 1 and not text.strip():
        try:
            image = PhraseImage.from_html_src(images[0])
            if image:
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, image.to_dib())
        except Exception:
            logging.exception("Failed setting clipboard image format.")


def _read_open_clipboard():
    saved = {}
    try:
        saved["text"] = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    except Exception:
        pass
    try:
        saved["html"] = win32clipboard.GetClipboardData(_get_cf_html())
    except TypeError:
        pass
    except Exception:
        logging.exception("Failed reading clipboard HTML.")
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
            saved["dib"] = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
    except Exception:
        logging.exception("Failed reading clipboard image.")
    return saved


def save_clipboard():
    """Save current clipboard text, HTML, and bitmap when available."""
    if not _open_clipboard():
        return {}
    try:
        return _read_open_clipboard()
    finally:
        win32clipboard.CloseClipboard()


def restore_clipboard(saved):
    """Restore clipboard from saved dict."""
    if not _open_clipboard():
        return
    try:
        win32clipboard.EmptyClipboard()
        if saved.get("text") is not None:
            win32clipboard.SetClipboardText(saved["text"], win32clipboard.CF_UNICODETEXT)
        if saved.get("html"):
            html = saved["html"]
            win32clipboard.SetClipboardData(_get_cf_html(), html.encode("utf-8") if isinstance(html, str) else html)
        if saved.get("dib"):
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, saved["dib"])
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_html(html_fragment):
    """Set clipboard to plain text + CF_HTML."""
    if not _open_clipboard():
        return False
    try:
        _write_open_clipboard(html_fragment)
        return True
    except Exception:
        logging.exception("set_clipboard_html: failed.")
        return False
    finally:
        win32clipboard.CloseClipboard()


def _is_phrase_dialog_active():
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


def save_and_set_clipboard_html(html_fragment):
    """
    Save current clipboard and set it to *html_fragment* in a single open/close.

    Returns ``(saved_dict, html_ok)``.  Using a single open/close is ~5 ms faster
    than the two-call save+set sequence, which matters for keeping the _sending
    window short in the auto-expand path.
    """
    saved = {}
    html_ok = False
    if not html_fragment or not html_fragment.strip():
        saved = save_clipboard()
        return saved, False
    if not _open_clipboard():
        return saved, False
    try:
        saved = _read_open_clipboard()
        try:
            _write_open_clipboard(html_fragment)
            html_ok = True
        except Exception:
            logging.exception("save_and_set: failed setting clipboard data.")
    finally:
        win32clipboard.CloseClipboard()
    return saved, html_ok


def paste_rich_text(html_fragment):
    """
    Save clipboard, set phrase HTML to clipboard, send Ctrl+V, restore clipboard.
    Run in a short-delay thread so the calling key handler returns first.
    """
    if not (html_fragment and html_fragment.strip()):
        return
    if _is_phrase_dialog_active():
        return

    def do_paste():
        time.sleep(0.05)
        saved = save_clipboard()
        try:
            ok = set_clipboard_html(html_fragment)
            if not ok:
                try:
                    Controller().type(html_to_plain(html_fragment))
                except Exception:
                    logging.exception("Failed fallback typing plain text expansion.")
                return
            time.sleep(0.02)
            _ensure_shift_released_before_ctrl_v()
            ctrl = Controller()
            ctrl.press(Key.ctrl)
            ctrl.press("v")
            ctrl.release("v")
            ctrl.release(Key.ctrl)
            time.sleep(0.2)
        finally:
            restore_clipboard(saved)

    threading.Thread(target=do_paste, daemon=True).start()
