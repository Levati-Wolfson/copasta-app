"""Rich text paste: save clipboard, set HTML + plain text, Ctrl+V, restore. Uses Windows CF_HTML."""
import re
import time
import threading
import logging
import ctypes

import win32clipboard
from pynput.keyboard import Controller, Key

CF_HTML = None


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
    ) % (html_fragment or "")
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


def html_to_plain(html):
    """Strip tags for plain-text fallback."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text.strip()


def save_clipboard():
    """Save current clipboard. Returns dict with keys 'text' and 'html' (optional)."""
    saved = {}
    if not _open_clipboard():
        return saved
    try:
        try:
            saved["text"] = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except Exception:
            saved["text"] = ""
        try:
            html = win32clipboard.GetClipboardData(_get_cf_html())
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")
            saved["html"] = html
        except TypeError:
            pass
        except Exception:
            logging.exception("save_clipboard: failed reading HTML.")
    finally:
        win32clipboard.CloseClipboard()
    return saved


def restore_clipboard(saved):
    """Restore clipboard from saved dict."""
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
    """Set clipboard to plain text + CF_HTML."""
    if not _open_clipboard():
        return False
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(html_to_plain(html_fragment), win32clipboard.CF_UNICODETEXT)
        try:
            win32clipboard.SetClipboardData(_get_cf_html(), _build_cf_html_content(html_fragment))
        except Exception:
            logging.exception("set_clipboard_html: failed setting HTML format.")
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
        # ── save ──────────────────────────────────────────────────────────
        try:
            saved["text"] = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except Exception:
            saved["text"] = ""
        try:
            raw = win32clipboard.GetClipboardData(_get_cf_html())
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            saved["html"] = raw
        except TypeError:
            pass
        except Exception:
            logging.exception("save_and_set: failed reading HTML.")
        # ── set ───────────────────────────────────────────────────────────
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(html_to_plain(html_fragment), win32clipboard.CF_UNICODETEXT)
            try:
                win32clipboard.SetClipboardData(_get_cf_html(), _build_cf_html_content(html_fragment))
            except Exception:
                logging.exception("save_and_set: HTML format failed; plain text set.")
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
            ctrl = Controller()
            ctrl.press(Key.ctrl)
            ctrl.press("v")
            ctrl.release("v")
            ctrl.release(Key.ctrl)
            time.sleep(0.2)
        finally:
            restore_clipboard(saved)

    threading.Thread(target=do_paste, daemon=True).start()
