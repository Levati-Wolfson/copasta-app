"""Rich text editor widget: toolbar (Bold, Italic, Underline, etc.) and Text with HTML export."""
import html as html_module
import tkinter as tk
import webbrowser
import ctypes
from tkinter import font as tkfont
from html.parser import HTMLParser
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# Shared rich-text clipboard for cross-editor paste within the same process.
# "spans" is a list of (text, frozenset_of_tags, link_url_or_None).
# "seq"   is the Windows clipboard sequence number at the time of the copy,
#         used to detect whether the system clipboard has changed since then.
_rich_clipboard = {"plain": None, "spans": None, "seq": None}


# Tag names and HTML tags
TAG_BOLD = "bold"
TAG_ITALIC = "italic"
TAG_UNDERLINE = "underline"
TAG_SUBSCRIPT = "sub"
TAG_SUPERSCRIPT = "sup"
TAG_LINK = "link"
TAG_BULLET = "bullet"
TAG_NUMBER = "number"
TAG_BOLDITALIC = "bold_italic"

TAG_TO_HTML = {
    TAG_BOLD: ("<b>", "</b>"),
    TAG_ITALIC: ("<i>", "</i>"),
    TAG_UNDERLINE: ("<u>", "</u>"),
    TAG_SUBSCRIPT: ("<sub>", "</sub>"),
    TAG_SUPERSCRIPT: ("<sup>", "</sup>"),
    TAG_LINK: ('<a href="%s">', "</a>"),
}
INLINE_TAG_ORDER = [TAG_BOLD, TAG_ITALIC, TAG_UNDERLINE, TAG_SUBSCRIPT, TAG_SUPERSCRIPT, TAG_LINK]


def _escape_html(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _unescape_html(s):
    return (
        s.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )


def _is_safe_url(url):
    """Only allow http/https URLs to be opened in the browser."""
    return url.lower().startswith(("http://", "https://"))


def _apply_dark_titlebar(window):
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        use_dark_mode = ctypes.c_int(1)
        for attr in (20, 19):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(use_dark_mode), ctypes.sizeof(use_dark_mode)
                )
                break
            except Exception:
                continue
    except Exception:
        pass


def _ask_hyperlink_dialog(parent, initial_url):
    result = {"value": None}
    d = tk.Toplevel(parent)
    d.title("Hyperlink")
    d.transient(parent)
    d.grab_set()
    d.resizable(False, False)
    _apply_dark_titlebar(d)

    frame = ttk.Frame(d, padding="10 10 10 10")
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text="URL:").pack(anchor=tk.W)
    var = tk.StringVar(value=initial_url or "https://")
    entry = ttk.Entry(frame, textvariable=var, width=44)
    entry.pack(fill=tk.X, pady=(6, 10))
    entry.selection_range(0, tk.END)
    entry.focus_set()

    btns = ttk.Frame(frame)
    btns.pack(fill=tk.X)

    def on_ok():
        result["value"] = var.get().strip()
        d.destroy()

    def on_cancel():
        result["value"] = None
        d.destroy()

    ttk.Button(btns, text="OK", command=on_ok, bootstyle="primary").pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btns, text="Cancel", command=on_cancel, bootstyle="secondary").pack(side=tk.LEFT)
    d.bind("<Return>", lambda _e: on_ok())
    d.bind("<Escape>", lambda _e: on_cancel())
    d.protocol("WM_DELETE_WINDOW", on_cancel)
    d.after(10, lambda: d.geometry("+%d+%d" % (parent.winfo_rootx() + 40, parent.winfo_rooty() + 40)))
    parent.wait_window(d)
    return result["value"]


class RichTextEditor(ttk.Frame):
    """Frame containing toolbar + Text with tags. get_html() returns HTML fragment."""

    def __init__(self, parent, height=12, show_toolbar=True, readonly=False, font_size_offset=0, text_width=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._height = height
        self._readonly = bool(readonly)
        self._text_width = text_width
        self._link_url = tk.StringVar(value="https://")
        self._link_tooltip = None
        self._link_tooltip_text = ""
        self._font_offset = int(font_size_offset)
        self._style = ttk.Style()
        # ttk.Button does not support per-widget font via configure(font=...),
        # so define dedicated styles for the B/I/U buttons.
        self._apply_toolbar_fonts()
        self._show_toolbar = bool(show_toolbar)
        if self._show_toolbar:
            self._build_toolbar()
        self._build_text()
        self._text.bind("<Control-b>", lambda e: self._toggle_tag_shortcut(TAG_BOLD))
        self._text.bind("<Control-B>", lambda e: self._toggle_tag_shortcut(TAG_BOLD))
        self._text.bind("<Control-i>", lambda e: self._toggle_tag_shortcut(TAG_ITALIC))
        self._text.bind("<Control-I>", lambda e: self._toggle_tag_shortcut(TAG_ITALIC))
        self._text.bind("<Control-u>", lambda e: self._toggle_tag_shortcut(TAG_UNDERLINE))
        self._text.bind("<Control-U>", lambda e: self._toggle_tag_shortcut(TAG_UNDERLINE))
        self._text.bind("<Control-z>", lambda e: self._undo())
        self._text.bind("<Control-y>", lambda e: self._redo())
        self._text.bind("<Control-Shift-Z>", lambda e: self._redo())
        self._text.bind("<Control-Shift-z>", lambda e: self._redo())
        self._text.bind("<Control-c>", lambda e: self._on_copy())
        self._text.bind("<Control-C>", lambda e: self._on_copy())
        self._text.bind("<Control-x>", lambda e: self._on_cut())
        self._text.bind("<Control-X>", lambda e: self._on_cut())
        self._text.bind("<Control-v>", lambda e: self._on_paste())
        self._text.bind("<Control-V>", lambda e: self._on_paste())
        self._text.bind("<Motion>", self._on_text_motion)
        self._text.bind("<Leave>", lambda e: self._hide_link_tooltip())
        self._text.bind("<Button-1>", self._on_text_click)
        if self._readonly:
            self.set_readonly(True)

    def _build_toolbar(self):
        tb = ttk.Frame(self)
        tb.pack(fill=tk.X, pady=(0, 4))
        # Use ttkbootstrap buttons with modern dark styling
        b_undo = ttk.Button(tb, text="Undo", width=5, command=self._undo, bootstyle="secondary")
        b_undo.pack(side=tk.LEFT, padx=2)
        b_redo = ttk.Button(tb, text="Redo", width=5, command=self._redo, bootstyle="secondary")
        b_redo.pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        b_bold = ttk.Button(
            tb, text="B", width=2, command=lambda: self._toggle_tag(TAG_BOLD), bootstyle="secondary", style="EditorBold.TButton"
        )
        b_bold.pack(side=tk.LEFT, padx=2)
        b_italic = ttk.Button(
            tb, text="I", width=2, command=lambda: self._toggle_tag(TAG_ITALIC), bootstyle="secondary", style="EditorItalic.TButton"
        )
        b_italic.pack(side=tk.LEFT, padx=2)
        b_ul = ttk.Button(
            tb, text="U", width=2, command=lambda: self._toggle_tag(TAG_UNDERLINE), bootstyle="secondary", style="EditorUnderline.TButton"
        )
        b_ul.pack(side=tk.LEFT, padx=2)
        b_sub = ttk.Button(tb, text="x\u2082", width=2, command=lambda: self._toggle_tag(TAG_SUBSCRIPT), bootstyle="secondary")
        b_sub.pack(side=tk.LEFT, padx=2)
        b_sup = ttk.Button(tb, text="x\u00b2", width=2, command=lambda: self._toggle_tag(TAG_SUPERSCRIPT), bootstyle="secondary")
        b_sup.pack(side=tk.LEFT, padx=2)
        b_link = ttk.Button(tb, text="Link", width=4, command=self._add_link, bootstyle="secondary")
        b_link.pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        b_bullet = ttk.Button(tb, text="\u2022", width=2, command=lambda: self._insert_list(True), bootstyle="secondary")
        b_bullet.pack(side=tk.LEFT, padx=2)
        b_num = ttk.Button(tb, text="1.", width=2, command=lambda: self._insert_list(False), bootstyle="secondary")
        b_num.pack(side=tk.LEFT, padx=2)

    def _build_text(self):
        text_frame = ttk.Frame(self)
        text_frame.pack(fill=tk.BOTH, expand=True)
        # Manually style Text widget for dark mode
        text_kw = dict(
            wrap=tk.WORD,
            height=self._height,
            font=("Segoe UI", 10 + self._font_offset),
            padx=6,
            pady=6,
            undo=True,
            bg="#2b2b2b",
            fg="#ffffff",
            insertbackground="#ffffff",
            selectbackground="#505050",
            selectforeground="#ffffff",
        )
        if self._text_width is not None:
            text_kw["width"] = int(self._text_width)
        self._text = tk.Text(
            text_frame,
            **text_kw,
        )
        scroll = ttk.Scrollbar(text_frame)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text.config(yscrollcommand=scroll.set)
        scroll.config(command=self._text.yview)
        self._apply_text_fonts()

    def _apply_toolbar_fonts(self):
        b = 10 + self._font_offset
        self._style.configure("EditorBold.TButton", font=("Segoe UI", b, "bold"))
        self._style.configure("EditorItalic.TButton", font=("Segoe UI", b, "italic"))
        self._style.configure("EditorUnderline.TButton", font=("Segoe UI", b, "underline"))

    def _apply_text_fonts(self):
        b = 10 + self._font_offset
        s = 8 + self._font_offset
        self._text.configure(font=("Segoe UI", b))
        self._text.tag_configure(TAG_BOLD, font=("Segoe UI", b, "bold"))
        self._text.tag_configure(TAG_ITALIC, font=("Segoe UI", b, "italic"))
        self._text.tag_configure(TAG_BOLDITALIC, font=("Segoe UI", b, "bold italic"))
        self._text.tag_configure(TAG_UNDERLINE, underline=True)
        self._text.tag_configure(TAG_SUBSCRIPT, offset=-4, font=("Segoe UI", s))
        self._text.tag_configure(TAG_SUPERSCRIPT, offset=4, font=("Segoe UI", s))
        self._text.tag_configure(TAG_LINK, foreground="#6eb4ff", underline=True)
        self._text.tag_raise(TAG_BOLDITALIC)

    def apply_font_size(self, font_size_offset):
        """Re-apply all fonts with a new offset (0=small, 2=medium, 4=large)."""
        self._font_offset = int(font_size_offset)
        self._apply_toolbar_fonts()
        self._apply_text_fonts()

    # ------------------------------------------------------------------
    # Rich copy / cut / paste
    # ------------------------------------------------------------------

    def _clipboard_seq(self):
        """Return the Windows clipboard sequence number (increments on every change)."""
        try:
            import win32clipboard
            return win32clipboard.GetClipboardSequenceNumber()
        except Exception:
            return None

    def _get_selection_spans(self, start, end):
        """Return [(text, frozenset_of_tags, link_url_or_None)] for the range [start, end)."""
        content = self._text.get(start, end)
        if not content:
            return []
        spans = []
        run_text = ""
        run_tags = None
        run_link = None
        start_norm = self._text.index(start)
        for i, ch in enumerate(content):
            pos = "%s+%dc" % (start_norm, i)
            names = self._text.tag_names(pos)
            inline = frozenset(t for t in names if t in INLINE_TAG_ORDER)
            link = next((_unescape_html(t[5:]) for t in names if t.startswith("link_")), None)
            if run_tags is None:
                run_tags, run_link, run_text = inline, link, ch
            elif inline == run_tags and link == run_link:
                run_text += ch
            else:
                spans.append((run_text, run_tags, run_link))
                run_tags, run_link, run_text = inline, link, ch
        if run_text:
            spans.append((run_text, run_tags, run_link))
        return spans

    def _insert_spans_at_cursor(self, spans):
        """Delete any current selection, then insert formatted spans at the cursor."""
        if self._readonly:
            return
        try:
            sel = self._text.tag_ranges(tk.SEL)
            if sel:
                self._text.delete(sel[0], sel[1])
        except tk.TclError:
            pass
        for text, inline_tags, link_url in spans:
            if not text:
                continue
            pos_start = self._text.index(tk.INSERT)
            self._text.insert(tk.INSERT, text)
            pos_end = self._text.index(tk.INSERT)
            for tag in inline_tags:
                self._text.tag_add(tag, pos_start, pos_end)
            if link_url and TAG_LINK in inline_tags:
                self._text.tag_add("link_%s" % _escape_html(link_url), pos_start, pos_end)
        self._refresh_derived_tags()

    def _on_copy(self, event=None):
        sel = self._text.tag_ranges(tk.SEL)
        if not sel:
            return "break"
        start, end = sel[0], sel[1]
        plain = self._text.get(start, end)
        spans = self._get_selection_spans(start, end)
        self._text.clipboard_clear()
        self._text.clipboard_append(plain)
        _rich_clipboard["plain"] = plain
        _rich_clipboard["spans"] = spans
        _rich_clipboard["seq"] = self._clipboard_seq()
        return "break"

    def _on_cut(self, event=None):
        if self._readonly:
            return "break"
        sel = self._text.tag_ranges(tk.SEL)
        if not sel:
            return "break"
        self._on_copy()
        try:
            sel = self._text.tag_ranges(tk.SEL)
            if sel:
                self._text.delete(sel[0], sel[1])
                self._refresh_derived_tags()
        except tk.TclError:
            pass
        return "break"

    def _on_paste(self, event=None):
        if self._readonly:
            return "break"
        current_seq = self._clipboard_seq()
        use_rich = (
            _rich_clipboard["spans"] is not None
            and _rich_clipboard["seq"] is not None
            and current_seq is not None
            and current_seq == _rich_clipboard["seq"]
        )
        # Fallback: if sequence numbers unavailable, compare plain text
        if not use_rich and _rich_clipboard["plain"] is not None:
            try:
                use_rich = (self._text.clipboard_get() == _rich_clipboard["plain"]
                            and _rich_clipboard["spans"] is not None)
            except tk.TclError:
                pass
        if use_rich:
            self._insert_spans_at_cursor(_rich_clipboard["spans"])
        else:
            _rich_clipboard.update({"plain": None, "spans": None, "seq": None})
            try:
                text = self._text.clipboard_get()
            except tk.TclError:
                return "break"
            try:
                sel = self._text.tag_ranges(tk.SEL)
                if sel:
                    self._text.delete(sel[0], sel[1])
            except tk.TclError:
                pass
            self._text.insert(tk.INSERT, text)
        return "break"

    def set_readonly(self, value=True):
        self._readonly = bool(value)
        self._text.configure(state=(tk.DISABLED if self._readonly else tk.NORMAL))

    def _toggle_tag_shortcut(self, tag_name):
        self._toggle_tag(tag_name)
        return "break"

    def _refresh_derived_tags(self):
        """Refresh rendered combined-style tags (currently bold+italic)."""
        self._text.tag_remove(TAG_BOLDITALIC, "1.0", tk.END)
        end = self._text.index("end-1c")
        if self._text.compare(end, "<=", "1.0"):
            return
        i = "1.0"
        run_start = None
        while self._text.compare(i, "<", end):
            tags = set(self._text.tag_names(i))
            both = TAG_BOLD in tags and TAG_ITALIC in tags
            if both and run_start is None:
                run_start = i
            if (not both) and run_start is not None:
                self._text.tag_add(TAG_BOLDITALIC, run_start, i)
                run_start = None
            i = self._text.index("%s+1c" % i)
        if run_start is not None:
            self._text.tag_add(TAG_BOLDITALIC, run_start, end)
        self._text.tag_raise(TAG_BOLDITALIC)

    def _undo(self):
        try:
            self._text.edit_undo()
        except tk.TclError:
            pass
        return "break"

    def _redo(self):
        try:
            self._text.edit_redo()
        except tk.TclError:
            pass
        return "break"

    def _toggle_tag(self, tag_name):
        try:
            sel = self._text.tag_ranges(tk.SEL)
            if not sel:
                return
            start, end = sel[0], sel[1]
            # Toggle behavior: remove if entire selection already has the tag.
            ranges = self._text.tag_ranges(tag_name)
            fully_tagged = False
            for i in range(0, len(ranges), 2):
                r_start, r_end = ranges[i], ranges[i + 1]
                if self._text.compare(r_start, "<=", start) and self._text.compare(r_end, ">=", end):
                    fully_tagged = True
                    break
            if fully_tagged:
                self._text.tag_remove(tag_name, start, end)
            else:
                self._text.tag_add(tag_name, start, end)
            if tag_name in (TAG_BOLD, TAG_ITALIC):
                self._refresh_derived_tags()
        except Exception:
            pass

    def _add_link(self):
        initial_url = self._link_url.get()
        try:
            sel = self._text.tag_ranges(tk.SEL)
            if sel:
                for t in self._text.tag_names(sel[0]):
                    if t.startswith("link_"):
                        initial_url = _unescape_html(t[5:])
                        break
        except Exception:
            pass
        url = _ask_hyperlink_dialog(self.winfo_toplevel(), initial_url)
        if not url:
            return
        self._link_url.set(url)
        try:
            sel = self._text.tag_ranges(tk.SEL)
            if sel:
                # Replace old per-link tags in the selected span.
                for t in self._text.tag_names(sel[0]):
                    if t.startswith("link_"):
                        self._text.tag_remove(t, sel[0], sel[1])
                self._text.tag_add(TAG_LINK, sel[0], sel[1])
                self._text.tag_add("link_%s" % _escape_html(url), sel[0], sel[1])
            else:
                pos = self._text.index(tk.INSERT)
                self._text.insert(pos, url)
                self._text.tag_add(TAG_LINK, pos, "%s+%dc" % (pos, len(url)))
                self._text.tag_add("link_%s" % _escape_html(url), pos, "%s+%dc" % (pos, len(url)))
        except Exception:
            pass

    def _insert_list(self, bullet):
        try:
            pos = self._text.index(tk.INSERT)
            line = self._text.get("%s linestart" % pos, "%s lineend" % pos)
            if bullet:
                prefix = "• "
            else:
                prefix = "1. "
            self._text.insert("%s linestart" % pos, prefix)
            self._text.tag_add(TAG_BULLET if bullet else TAG_NUMBER, "%s linestart" % pos, "%s linestart +%dc" % (pos, len(prefix)))
        except Exception:
            pass

    def _on_text_motion(self, event):
        try:
            idx = self._text.index("@%d,%d" % (event.x, event.y))
            names = self._text.tag_names(idx)
            if TAG_LINK not in names:
                if self._readonly:
                    self._text.configure(cursor="xterm")
                self._hide_link_tooltip()
                return
            url = None
            for t in names:
                if t.startswith("link_"):
                    url = _unescape_html(t[5:])
                    break
            if not url:
                if self._readonly:
                    self._text.configure(cursor="xterm")
                self._hide_link_tooltip()
                return
            if self._readonly:
                self._text.configure(cursor="hand2")
            self._show_link_tooltip(url, event.x_root + 12, event.y_root + 12)
        except Exception:
            self._hide_link_tooltip()
            if self._readonly:
                self._text.configure(cursor="xterm")

    def _on_text_click(self, event):
        if not self._readonly:
            return
        try:
            idx = self._text.index("@%d,%d" % (event.x, event.y))
            names = self._text.tag_names(idx)
            if TAG_LINK not in names:
                return
            for t in names:
                if t.startswith("link_"):
                    url = _unescape_html(t[5:])
                    if url and _is_safe_url(url):
                        webbrowser.open(url)
                    break
        except Exception:
            pass
        return "break"

    def _show_link_tooltip(self, text, x, y):
        if self._link_tooltip and self._link_tooltip_text == text:
            self._link_tooltip.geometry("+%d+%d" % (x, y))
            return
        self._hide_link_tooltip()
        tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg="#1f1f1f", highlightthickness=1, highlightbackground="#6eb4ff")
        lbl = tk.Label(tip, text=text, bg="#1f1f1f", fg="#d8d8d8", padx=6, pady=3, font=("Segoe UI", 9))
        lbl.pack()
        tip.geometry("+%d+%d" % (x, y))
        self._link_tooltip = tip
        self._link_tooltip_text = text

    def _hide_link_tooltip(self):
        if self._link_tooltip:
            try:
                self._link_tooltip.destroy()
            except Exception:
                pass
            self._link_tooltip = None
            self._link_tooltip_text = ""

    def get_html(self):
        """Export Text content with robust nested HTML tags."""
        content = self._text.get("1.0", "end-1c")
        if not content:
            return "<p></p>"

        def tags_at(pos):
            names = self._text.tag_names(pos)
            wanted = [t for t in names if t in INLINE_TAG_ORDER]
            link_url = None
            if TAG_LINK in wanted:
                for t in names:
                    if t.startswith("link_"):
                        link_url = _unescape_html(t[5:])
                        break
            wanted_sorted = [t for t in INLINE_TAG_ORDER if t in wanted]
            return wanted_sorted, link_url

        def open_tag(tag, link_url):
            if tag == TAG_LINK:
                href = _escape_html(link_url or "https://")
                return '<a href="%s">' % href
            return TAG_TO_HTML[tag][0]

        def close_tag(tag):
            return TAG_TO_HTML[tag][1]

        out = []
        open_stack = []
        open_link_url = None

        for idx, ch in enumerate(content):
            pos = "1.0+%dc" % idx
            desired_tags, desired_link_url = tags_at(pos)

            while open_stack and open_stack[-1] not in desired_tags:
                closing = open_stack.pop()
                out.append(close_tag(closing))
                if closing == TAG_LINK:
                    open_link_url = None

            for tag in desired_tags:
                if tag in open_stack:
                    if tag == TAG_LINK and open_link_url != desired_link_url:
                        while open_stack and open_stack[-1] != TAG_LINK:
                            out.append(close_tag(open_stack.pop()))
                        if open_stack and open_stack[-1] == TAG_LINK:
                            out.append(close_tag(open_stack.pop()))
                        out.append(open_tag(TAG_LINK, desired_link_url))
                        open_stack.append(TAG_LINK)
                        open_link_url = desired_link_url
                    continue
                out.append(open_tag(tag, desired_link_url))
                open_stack.append(tag)
                if tag == TAG_LINK:
                    open_link_url = desired_link_url

            if ch == "\n":
                out.append("<br>")
            else:
                out.append(_escape_html(ch))

        while open_stack:
            out.append(close_tag(open_stack.pop()))

        html = "".join(out).strip()
        return html if html else "<p></p>"

    def set_html(self, html_fragment):
        """Import basic HTML into the editor and restore text tags."""

        class _ImportParser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.chunks = []  # list[(text, tags, link_url)]
                self.active_tags = []
                self.active_link = None

            def _append_text(self, text):
                if not text:
                    return
                tags = tuple(sorted(set(self.active_tags)))
                self.chunks.append((text, tags, self.active_link))

            def _append_newline_once(self):
                if not self.chunks:
                    return
                last_text, last_tags, last_link = self.chunks[-1]
                if last_text.endswith("\n"):
                    return
                self.chunks[-1] = (last_text + "\n", last_tags, last_link)

            def handle_starttag(self, tag, attrs):
                t = tag.lower()
                if t == "b":
                    self.active_tags.append(TAG_BOLD)
                elif t == "i":
                    self.active_tags.append(TAG_ITALIC)
                elif t == "u":
                    self.active_tags.append(TAG_UNDERLINE)
                elif t == "sub":
                    self.active_tags.append(TAG_SUBSCRIPT)
                elif t == "sup":
                    self.active_tags.append(TAG_SUPERSCRIPT)
                elif t == "a":
                    href = ""
                    for k, v in attrs:
                        if (k or "").lower() == "href":
                            href = v or ""
                            break
                    self.active_tags.append(TAG_LINK)
                    self.active_link = href
                elif t == "br":
                    self._append_text("\n")
                elif t == "li":
                    self._append_text("• ")

            def handle_endtag(self, tag):
                t = tag.lower()
                if t == "b" and TAG_BOLD in self.active_tags:
                    self.active_tags.remove(TAG_BOLD)
                elif t == "i" and TAG_ITALIC in self.active_tags:
                    self.active_tags.remove(TAG_ITALIC)
                elif t == "u" and TAG_UNDERLINE in self.active_tags:
                    self.active_tags.remove(TAG_UNDERLINE)
                elif t == "sub" and TAG_SUBSCRIPT in self.active_tags:
                    self.active_tags.remove(TAG_SUBSCRIPT)
                elif t == "sup" and TAG_SUPERSCRIPT in self.active_tags:
                    self.active_tags.remove(TAG_SUPERSCRIPT)
                elif t == "a":
                    if TAG_LINK in self.active_tags:
                        self.active_tags.remove(TAG_LINK)
                    self.active_link = None
                elif t in ("li",):
                    self._append_newline_once()

            def handle_data(self, data):
                if data in ("\n", "\r\n", "\r"):
                    return
                self._append_text(data)

        parser = _ImportParser()
        parser.feed(html_fragment or "")
        parser.close()

        # Trim trailing newlines to avoid line growth on repeated save/load cycles.
        while parser.chunks and parser.chunks[-1][0] in ("\n", "\r\n"):
            parser.chunks.pop()
        if parser.chunks:
            t, tg, lk = parser.chunks[-1]
            parser.chunks[-1] = (t.rstrip("\n"), tg, lk)

        prev_state = self._text.cget("state")
        if prev_state == tk.DISABLED:
            self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        for text, tags, link_url in parser.chunks:
            if not text:
                continue
            start = self._text.index("end-1c")
            self._text.insert("end", text)
            end = self._text.index("end-1c")
            if self._text.compare(start, ">=", end):
                continue
            for tag in tags:
                self._text.tag_add(tag, start, end)
            if TAG_LINK in tags and link_url:
                self._text.tag_add("link_%s" % _escape_html(link_url), start, end)
        self._refresh_derived_tags()
        if prev_state == tk.DISABLED:
            self._text.configure(state=tk.DISABLED)

    def get_plain(self):
        return self._text.get("1.0", tk.END).strip()

    def clear(self):
        self._text.delete("1.0", tk.END)
