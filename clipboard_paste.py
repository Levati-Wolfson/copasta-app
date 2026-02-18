"""Rich text paste: save clipboard, set HTML, Ctrl+V, restore. Uses Windows CF_HTML."""
import time
import threading
import logging
import ctypes

import win32clipboard
from pynput.keyboard import Controller, Key

# CF_HTML is not a constant in win32clipboard; we register it
CF_HTML = None


def _get_cf_html():
    global CF_HTML
    if CF_HTML is None:
        CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")
    return CF_HTML


def _build_cf_html_content(html_fragment):
    """Build CF_HTML bytes with correct byte offsets."""
    body = "<html><body><!--StartFragment-->%s<!--EndFragment--></body></html>" % (html_fragment or "")
    header_tpl = "Version:0.9\r\nStartHTML:%09d\r\nEndHTML:%09d\r\nStartFragment:%09d\r\nEndFragment:%09d\r\n\r\n"
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


def save_clipboard():
    """Save current clipboard. Returns dict with keys 'text', 'html' (optional)."""
    saved = {}
    if not _open_clipboard():
        return saved
    try:
        try:
            text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            saved["text"] = text
        except Exception:
            saved["text"] = ""
        try:
            html = win32clipboard.GetClipboardData(_get_cf_html())
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")
            saved["html"] = html
        except TypeError:
            # Normal when clipboard currently has no HTML format.
            pass
        except Exception:
            logging.exception("Failed reading HTML data from clipboard.")
    finally:
        win32clipboard.CloseClipboard()
    return saved


def restore_clipboard(saved):
    """Restore clipboard from saved dict (text, optional html)."""
    if not _open_clipboard():
        return
    try:
        win32clipboard.EmptyClipboard()
        if saved.get("text") is not None:
            win32clipboard.SetClipboardText(saved["text"], win32clipboard.CF_UNICODETEXT)
        if saved.get("html"):
            win32clipboard.SetClipboardData(_get_cf_html(), saved["html"].encode("utf-8"))
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_html(html_fragment):
    """Set clipboard to HTML fragment (body content)."""
    if not _open_clipboard():
        return False
    try:
        win32clipboard.EmptyClipboard()
        data = _build_cf_html_content(html_fragment)
        plain = html_to_plain(html_fragment)
        # Always set plain text fallback first; then try HTML format.
        win32clipboard.SetClipboardText(plain, win32clipboard.CF_UNICODETEXT)
        try:
            win32clipboard.SetClipboardData(_get_cf_html(), data)
        except Exception:
            logging.exception("Failed setting HTML clipboard format; falling back to plain text.")
            return True
        return True
    except Exception:
        logging.exception("Failed setting clipboard data for rich paste.")
        return False
    finally:
        win32clipboard.CloseClipboard()


def html_to_plain(html):
    """Strip tags for plain-text fallback."""
    import re
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text.strip()


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
                # Absolute fallback: type plain text so expansion never becomes delete-only.
                try:
                    Controller().type(html_to_plain(html_fragment))
                except Exception:
                    logging.exception("Failed fallback typing plain text expansion.")
                return
            time.sleep(0.02)
            ctrl = Controller()
            ctrl.press(Key.ctrl)
            ctrl.press("v")
            ctrl.release("v")
            ctrl.release(Key.ctrl)
            # Give target app (e.g. Word) enough time to consume clipboard payload.
            time.sleep(0.2)
        finally:
            restore_clipboard(saved)

    threading.Thread(target=do_paste, daemon=True).start()
