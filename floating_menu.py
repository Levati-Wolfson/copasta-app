"""Global floating phrase menu: borderless popup, cascade, hover preview, pin."""
import re
import logging
import tkinter as tk
import tkinter.font as tkFont
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

import app_icon


def _strip_html(html):
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text.strip()[:200]


class FloatingMenu:
    """Borderless popup with folder tree and phrase list. Pin and X buttons. Hover opens folders."""

    def __init__(self, get_data, get_settings, on_paste_phrase, on_save_position=None, on_close=None):
        self._get_data = get_data
        self._get_settings = get_settings
        self._on_paste = on_paste_phrase
        self._on_save_position = on_save_position
        self._on_close = on_close
        self._root = None
        self._pinned = False
        self._hover_timers = {}  # level -> after id (for folder open)
        self._hover_indices = {}  # level -> hovered index
        self._close_timers = {}  # level -> after id (for cascade close grace period)
        self._preview_timer = None
        self._preview_win = None
        self._cascade_levels = {}  # level>=1 -> {"win","listbox","items"}
        self._drag_pos = None
        self._drag_started = False
        self._pin_btn = None
        self._close_btn = None
        self._listbox = None
        self._items = []
        self._target_hwnd = None

    def _build(self):
        if self._root is not None:
            return
        self._root = tk.Toplevel()
        app_icon.apply_window_icon(self._root)
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#222222", highlightthickness=1, highlightbackground="#444444")
        # Top row with title and buttons
        top_frame = ttk.Frame(self._root)
        top_frame.pack(fill=tk.X, padx=4, pady=4)
        self._header_label = ttk.Label(top_frame, text="Phrases", font=("Segoe UI", 10, "bold"))
        self._header_label.pack(side=tk.LEFT, padx=4)
        self._close_btn = ttk.Button(top_frame, text="✖", width=2, command=self._hide, bootstyle="secondary")
        self._close_btn.pack(side=tk.RIGHT, padx=1)
        self._pin_btn = ttk.Button(top_frame, text="📌", width=2, command=self._toggle_pin, bootstyle="secondary")
        self._pin_btn.pack(side=tk.RIGHT, padx=2)
        # List frame: root folders and phrases
        list_frame = ttk.Frame(self._root)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=6)
        self._listbox = tk.Listbox(
            list_frame,
            height=8,
            width=28,
            font=("Segoe UI", 10),
            bg="#2b2b2b",
            fg="#ffffff",
            selectbackground="#375a7f",
            selectforeground="#ffffff",
            activestyle="none",
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(list_frame)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.config(yscrollcommand=scroll.set)
        scroll.config(command=self._listbox.yview)
        self._bind_listbox(self._listbox, 0)
        # Draggable always
        top_frame.bind("<Button-1>", self._on_title_press)
        top_frame.bind("<B1-Motion>", self._on_title_motion)
        top_frame.bind("<ButtonRelease-1>", self._on_title_release)
        self._root.protocol("WM_DELETE_WINDOW", self._hide)
        self._root.bind("<FocusOut>", self._on_root_focus_out)
        self._root.bind("<Escape>", lambda e: self._hide())

    def _font_offset(self):
        return {"small": 0, "medium": 2, "large": 4}.get(
            self._get_settings().get("font_size", "small"), 0
        )

    def _fit_listbox_to_content(self, listbox, texts, min_chars=22, max_px=600):
        """Resize listbox width (in chars) to fit the longest entry."""
        if not texts:
            return
        try:
            font = tkFont.Font(font=listbox.cget("font"))
            max_text_px = min(max(font.measure(t) for t in texts), max_px)
            char_px = font.measure("0") or 7
            listbox.config(width=max(min_chars, max_text_px // char_px + 3))
        except Exception:
            logging.exception("Failed to fit listbox to content.")

    def _bind_listbox(self, listbox, level):
        listbox.bind("<Button-1>", lambda e, lv=level: self._on_list_click(lv, e))
        listbox.bind("<Motion>", lambda e, lv=level: self._on_list_motion(lv, e))
        listbox.bind("<Leave>", lambda e, lv=level: self._on_list_leave(lv, e))

    def _toggle_pin(self):
        self._set_pinned(not self._pinned)

    def _set_pinned(self, value):
        self._pinned = bool(value)
        if self._pin_btn:
            self._pin_btn.config(text="📍" if self._pinned else "📌")

    def _on_title_press(self, event):
        self._drag_pos = (event.x_root, event.y_root)
        self._drag_started = False

    def _on_title_motion(self, event):
        if self._drag_pos is None:
            return
        dx = event.x_root - self._drag_pos[0]
        dy = event.y_root - self._drag_pos[1]
        # Check if actually dragged (more than 3 pixels)
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_started = True
            # Auto-pin when dragging
            if not self._pinned:
                self._set_pinned(True)
        if self._drag_started:
            x = self._root.winfo_rootx() + dx
            y = self._root.winfo_rooty() + dy
            self._root.geometry("+%d+%d" % (x, y))
        self._drag_pos = (event.x_root, event.y_root)

    def _on_title_release(self, event):
        # Don't save position when dragging - only keep it pinned at current location
        self._drag_pos = None
        self._drag_started = False

    def _populate_root(self):
        self._listbox.delete(0, tk.END)
        self._items = []
        texts = []
        data = self._get_data()
        for item in data.get("children", []):
            name = item.get("name") or ("New Folder" if item.get("type") == "folder" else "(no name)")
            label = "  📁 " + name if item.get("type") == "folder" else "  📄 " + name
            self._listbox.insert(tk.END, label)
            self._items.append(item)
            texts.append(label)
        self._fit_listbox_to_content(self._listbox, texts)

    def _get_level_state(self, level):
        if level == 0:
            return {"win": self._root, "listbox": self._listbox, "items": self._items}
        return self._cascade_levels.get(level)

    def _cancel_hover_timer(self, level):
        tid = self._hover_timers.pop(level, None)
        if tid and self._root:
            try:
                self._root.after_cancel(tid)
            except Exception:
                logging.exception("Failed to cancel floating menu hover timer.")

    def _cancel_close_timer(self, level):
        tid = self._close_timers.pop(level, None)
        if tid and self._root:
            try:
                self._root.after_cancel(tid)
            except Exception:
                logging.exception("Failed to cancel floating menu close timer.")

    def _do_delayed_close(self, level):
        self._close_timers.pop(level, None)
        self._close_cascades_from(level)

    def _cancel_preview_timer(self):
        if self._preview_timer and self._root:
            try:
                self._root.after_cancel(self._preview_timer)
            except Exception:
                logging.exception("Failed to cancel floating menu preview timer.")
            self._preview_timer = None

    def _close_cascades_from(self, start_level):
        for lv in [l for l in list(self._close_timers.keys()) if l >= start_level]:
            self._cancel_close_timer(lv)
        for level in sorted([lv for lv in self._cascade_levels.keys() if lv >= start_level], reverse=True):
            win = self._cascade_levels[level]["win"]
            try:
                win.destroy()
            except Exception:
                logging.exception("Failed to destroy floating menu cascade window.")
            del self._cascade_levels[level]
            self._cancel_hover_timer(level)
            self._hover_indices.pop(level, None)

    def _on_list_click(self, level, event):
        state = self._get_level_state(level)
        if not state:
            return
        idx = state["listbox"].nearest(event.y)
        items = state["items"]
        if idx < 0 or idx >= len(items):
            return "break"
        item = items[idx]
        if item.get("type") == "phrase":
            self._run_phrase(item)
        # Clicking folder intentionally does nothing; open is hover-only
        return "break"

    def _on_list_motion(self, level, event):
        state = self._get_level_state(level)
        if not state:
            return
        listbox = state["listbox"]
        items = state["items"]
        idx = listbox.nearest(event.y)
        if idx < 0 or idx >= len(items):
            return
        if self._hover_indices.get(level) == idx:
            # Still on the same item — if it's a folder, make sure its cascade
            # isn't being scheduled for closing (e.g. cursor briefly left and returned).
            if items[idx].get("type") == "folder":
                self._cancel_close_timer(level + 1)
            return
        self._hover_indices[level] = idx
        self._cancel_hover_timer(level)
        self._cancel_preview_timer()
        item = items[idx]
        if item.get("type") == "folder":
            self._hide_preview()
            self._close_cascades_from(level + 1)
            self._open_folder_for_hover(level, idx)
        else:
            self._close_cascades_from(level + 1)
            self._preview_timer = self._root.after(
                500, lambda lv=level, i=idx: self._show_preview_for_item(lv, i)
            )

    def _on_list_leave(self, level, event):
        self._cancel_hover_timer(level)
        self._cancel_preview_timer()
        self._hide_preview()
        self._hover_indices.pop(level, None)
        # Schedule close of the child cascade after a grace period so that a
        # momentary slip of the cursor doesn't immediately dismiss it.
        child_level = level + 1
        if self._cascade_levels.get(child_level) and self._root:
            self._cancel_close_timer(child_level)
            self._close_timers[child_level] = self._root.after(
                500, lambda lv=child_level: self._do_delayed_close(lv)
            )

    def _open_folder_for_hover(self, level, idx):
        self._cancel_hover_timer(level)
        state = self._get_level_state(level)
        if not state:
            return
        items = state["items"]
        if idx < 0 or idx >= len(items):
            return
        folder_item = items[idx]
        if folder_item.get("type") != "folder":
            return
        self._open_cascade(level + 1, state["win"], state["listbox"], folder_item, idx)

    def _on_cascade_enter(self, level, event):
        """Cursor entered the cascade window — cancel pending close for this and all parent levels."""
        for lv in range(1, level + 1):
            self._cancel_close_timer(lv)

    def _on_cascade_leave(self, level, event):
        """Cursor left the cascade window — schedule a delayed close."""
        state = self._cascade_levels.get(level)
        if not state or not self._root:
            return
        win = state["win"]
        # Ignore internal leave events (cursor moving between child widgets).
        x, y = event.x_root, event.y_root
        wx, wy = win.winfo_rootx(), win.winfo_rooty()
        ww, wh = win.winfo_width(), win.winfo_height()
        if wx <= x < wx + ww and wy <= y < wy + wh:
            return
        self._cancel_close_timer(level)
        self._close_timers[level] = self._root.after(
            500, lambda lv=level: self._do_delayed_close(lv)
        )

    def _open_cascade(self, level, parent_win, parent_listbox, folder_item, row_idx):
        self._cancel_close_timer(level)
        self._close_cascades_from(level)
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#222222", highlightthickness=1, highlightbackground="#444444")
        frame = ttk.Frame(win, padding=6)
        frame.pack(fill=tk.BOTH, expand=True)
        items = list(folder_item.get("children", []))
        lb = tk.Listbox(
            frame,
            height=max(3, min(len(items), 15)),
            width=26,
            font=("Segoe UI", 10 + self._font_offset()),
            bg="#2b2b2b",
            fg="#ffffff",
            selectbackground="#375a7f",
            selectforeground="#ffffff",
            activestyle="none",
            highlightthickness=0,
        )
        lb.pack(fill=tk.BOTH, expand=True)
        texts = []
        for child in items:
            name = child.get("name") or ("New Folder" if child.get("type") == "folder" else "(no name)")
            label = "  📁 " + name if child.get("type") == "folder" else "  📄 " + name
            lb.insert(tk.END, label)
            texts.append(label)
        self._fit_listbox_to_content(lb, texts)
        self._bind_listbox(lb, level)
        win.bind("<Enter>", lambda e, lv=level: self._on_cascade_enter(lv, e))
        win.bind("<Leave>", lambda e, lv=level: self._on_cascade_leave(lv, e))
        self._cascade_levels[level] = {"win": win, "listbox": lb, "items": items}
        win.update_idletasks()
        bbox = parent_listbox.bbox(row_idx)
        if bbox:
            # Align the first item in the cascade with the hovered row in the parent.
            # Use the vertical center of the hovered row as the anchor point, then
            # subtract how far the center of cascade item 0 sits below the window top.
            row_center_y = parent_listbox.winfo_rooty() + bbox[1] + bbox[3] // 2
            lb_bbox0 = lb.bbox(0)
            if lb_bbox0:
                item0_center_offset = lb.winfo_y() + lb_bbox0[1] + lb_bbox0[3] // 2
            else:
                item0_center_offset = 6  # fallback: frame padding only
            row_y = row_center_y - item0_center_offset
        else:
            row_y = parent_win.winfo_rooty() + 30
        w = win.winfo_reqwidth()
        h = min(400, win.winfo_reqheight())
        x_right = parent_win.winfo_rootx() + parent_win.winfo_width() - 1
        x_left = parent_win.winfo_rootx() - w + 1
        _ml, _mt, _mr, _mb = self._get_monitor_rect(x_right, row_y)
        if x_right + w > _mr and x_left >= _ml:
            x = x_left
        else:
            x = x_right
        x, row_y = self._clamp_window_pos(x, row_y, w, h)
        win.geometry("%dx%d+%d+%d" % (w, h, x, row_y))

    def _run_phrase(self, phrase_item):
        self._cancel_preview_timer()
        self._hide_preview()
        self._close_cascades_from(1)
        if self._pinned:
            try:
                geom = self._root.geometry()
                self._root.withdraw()
                self._root.update()
                self._focus_target_window()
                self._on_paste(phrase_item)
                self._root.after(80, lambda g=geom: self._restore_after_pinned_paste(g))
            except Exception:
                self._on_paste(phrase_item)
        else:
            self._hide()
            self._focus_target_window()
            self._on_paste(phrase_item)

    def _restore_after_pinned_paste(self, geometry):
        try:
            self._root.deiconify()
            self._root.geometry(geometry)
            self._root.lift()
            self._root.attributes("-topmost", True)
        except Exception:
            logging.exception("Failed restoring pinned floating menu after paste.")

    def _show_preview_for_item(self, level, idx):
        self._preview_timer = None
        state = self._get_level_state(level)
        if not state:
            return
        items = state["items"]
        if idx < 0 or idx >= len(items):
            return
        phrase_item = items[idx]
        if phrase_item.get("type") != "phrase":
            return
        listbox = state["listbox"]
        win = state["win"]
        bbox = listbox.bbox(idx)
        if bbox:
            y = listbox.winfo_rooty() + bbox[1]
        else:
            y = win.winfo_rooty() + 20
        x = win.winfo_rootx() + win.winfo_width() + 8
        self._hide_preview()
        text = _strip_html(phrase_item.get("expansion_html") or "")
        if not text:
            return
        self._preview_win = tk.Toplevel(self._root)
        self._preview_win.overrideredirect(True)
        self._preview_win.attributes("-topmost", True)
        self._preview_win.configure(bg="#1a1a1a", highlightthickness=1, highlightbackground="#555555")
        lbl = tk.Label(
            self._preview_win,
            text=text,
            font=("Segoe UI", 9 + self._font_offset()),
            bg="#1a1a1a",
            fg="#dddddd",
            wraplength=280,
            justify=tk.LEFT,
            padx=8,
            pady=6,
        )
        lbl.pack(fill=tk.BOTH, expand=True)
        self._preview_win.geometry("+%d+%d" % (x, y))
        self._preview_win.update_idletasks()
        pw = self._preview_win.winfo_width()
        ph = self._preview_win.winfo_height()
        # Prefer right of the source window; flip left if it would go off screen
        _ml, _mt, _mr, _mb = self._get_monitor_rect(x, y)
        if x + pw > _mr:
            x_left = win.winfo_rootx() - pw - 8
            x = x_left if x_left >= _ml else max(_ml, _mr - pw)
        cx, cy = self._clamp_window_pos(x, y, pw, ph)
        if cx != x or cy != y:
            self._preview_win.geometry("+%d+%d" % (cx, cy))

    def _get_monitor_rect(self, x, y):
        """Return (left, top, right, bottom) of the work area of the monitor
        nearest to (x, y).  Falls back to the primary monitor on any error."""
        try:
            import ctypes
            import ctypes.wintypes

            class _MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", ctypes.wintypes.RECT),
                    ("rcWork", ctypes.wintypes.RECT),
                    ("dwFlags", ctypes.c_ulong),
                ]

            MONITOR_DEFAULTTONEAREST = 2
            hmon = ctypes.windll.user32.MonitorFromPoint(
                ctypes.wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST
            )
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
            r = info.rcWork
            return (r.left, r.top, r.right, r.bottom)
        except Exception:
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            return (0, 0, sw, sh)

    def _clamp_window_pos(self, x, y, w, h):
        """Return (x, y) adjusted so a w×h window stays fully on the monitor
        that contains (x, y)."""
        left, top, right, bottom = self._get_monitor_rect(x, y)
        x = max(left, min(x, right - w))
        y = max(top, min(y, bottom - h))
        return x, y

    def _hide_preview(self):
        if self._preview_win:
            try:
                self._preview_win.destroy()
            except Exception:
                logging.exception("Failed destroying floating menu preview window.")
            self._preview_win = None

    def _capture_target_window(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                self._target_hwnd = hwnd
        except Exception:
            self._target_hwnd = None

    def _focus_target_window(self):
        if not self._target_hwnd:
            return
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(self._target_hwnd)
        except Exception:
            logging.exception("Failed to focus target window for paste.")

    def _get_mouse_screen_pos(self):
        import ctypes
        from ctypes import byref
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(byref(pt))
        return pt.x, pt.y

    def _get_text_cursor_screen_pos(self):
        try:
            import ctypes
            from ctypes import byref, wintypes
            class GUITHREADINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND),
                    ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND),
                    ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT),
                ]
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            user32 = ctypes.windll.user32
            fg = user32.GetForegroundWindow()
            if not fg:
                return None
            tid = user32.GetWindowThreadProcessId(fg, None)
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not user32.GetGUIThreadInfo(tid, byref(info)):
                return None
            if not info.hwndCaret:
                return None
            pt = POINT(info.rcCaret.left, info.rcCaret.bottom)
            if not user32.ClientToScreen(info.hwndCaret, byref(pt)):
                return None
            return (pt.x, pt.y + 8)
        except Exception:
            return None

    def show(self, x=None, y=None):
        self._build()
        # Each open starts unpinned, even if it was pinned when closed.
        self._set_pinned(False)
        self._hover_indices.clear()
        # Re-apply font size in case the setting changed since last open.
        off = self._font_offset()
        b = 10 + off
        if self._header_label:
            self._header_label.configure(font=("Segoe UI", b, "bold"))
        if self._listbox:
            self._listbox.configure(font=("Segoe UI", b))
        self._populate_root()
        self._close_cascades_from(1)
        self._hide_preview()
        n = len(self._items)
        self._listbox.config(height=max(3, min(n, 20)))
        self._root.update_idletasks()
        self._capture_target_window()
        settings = self._get_settings()
        if x is not None and y is not None:
            px, py = x, y
        elif settings.get("floating_menu_position") == "fixed":
            px = settings.get("floating_menu_x", 100)
            py = settings.get("floating_menu_y", 100)
        elif settings.get("floating_menu_position") == "mouse":
            try:
                px, py = self._get_mouse_screen_pos()
            except Exception:
                px, py = 100, 100
        else:
            try:
                caret = self._get_text_cursor_screen_pos()
                if caret:
                    px, py = caret
                else:
                    px, py = self._get_mouse_screen_pos()
            except Exception:
                px, py = 100, 100
        w = self._root.winfo_reqwidth()
        h = self._root.winfo_reqheight()
        px, py = self._clamp_window_pos(px, py, w, h)
        self._root.geometry("+%d+%d" % (px, py))
        self._root.deiconify()
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.focus_force()

    def _on_root_focus_out(self, event):
        if self._pinned or not self._root:
            return
        self._root.after(150, self._maybe_hide_on_focus_loss)

    def _maybe_hide_on_focus_loss(self):
        if self._pinned or not self._root:
            return
        try:
            focused = self._root.focus_get()
        except Exception:
            focused = None
        if focused is None:
            self._hide()
            return
        our_windows = {self._root}
        for state in self._cascade_levels.values():
            w = state.get("win")
            if w:
                our_windows.add(w)
        if self._preview_win:
            our_windows.add(self._preview_win)
        widget = focused
        while widget is not None:
            if widget in our_windows:
                return
            try:
                widget = widget.master
            except AttributeError:
                break
        self._hide()

    def _hide(self):
        self._cancel_preview_timer()
        for level in list(self._hover_timers.keys()):
            self._cancel_hover_timer(level)
        for level in list(self._close_timers.keys()):
            self._cancel_close_timer(level)
        self._hide_preview()
        self._close_cascades_from(1)
        self._set_pinned(False)
        if self._root:
            self._root.withdraw()
        if self._on_close:
            self._on_close()

    def is_visible(self):
        return self._root and self._root.winfo_viewable()

    def destroy(self):
        self._cancel_preview_timer()
        for level in list(self._hover_timers.keys()):
            self._cancel_hover_timer(level)
        for level in list(self._close_timers.keys()):
            self._cancel_close_timer(level)
        self._hide_preview()
        self._close_cascades_from(1)
        if self._root:
            try:
                self._root.destroy()
            except Exception:
                logging.exception("Failed destroying floating menu root window.")
            self._root = None


def run_position_picker(parent, on_save_xy, on_close=None):
    """Show a semi-transparent draggable window; on Save store its position. on_close is called when window is closed."""
    win = tk.Toplevel(parent)
    app_icon.apply_window_icon(win)
    win.overrideredirect(True)
    win.attributes("-alpha", 0.6)
    win.attributes("-topmost", True)
    win.configure(bg="#2d5f7f")
    # Large enough for full text and button
    win.geometry("320x140+200+200")
    win.update_idletasks()
    tk.Label(win, text="Drag me to position, then click Save", bg="#2d5f7f", fg="white", font=("Segoe UI", 11)).pack(pady=20, padx=16)
    btn = ttk.Button(win, text="Save position", command=lambda: _save_pos(win, on_save_xy, on_close), bootstyle="primary")
    btn.pack(pady=8)

    closed = {"done": False}

    def _call_on_close_once():
        if closed["done"]:
            return
        closed["done"] = True
        if on_close:
            try:
                on_close()
            except Exception:
                logging.exception("Position picker on_close callback failed.")

    def _cleanup():
        try:
            win.destroy()
        except Exception:
            logging.exception("Failed destroying position picker window.")
        _call_on_close_once()

    def on_drag_start(event):
        win._drag_x, win._drag_y = event.x, event.y
        win._drag_root_x = win.winfo_rootx()
        win._drag_root_y = win.winfo_rooty()

    def on_drag_motion(event):
        if hasattr(win, "_drag_x"):
            dx = event.x - win._drag_x
            dy = event.y - win._drag_y
            x = win._drag_root_x + dx
            y = win._drag_root_y + dy
            win.geometry("+%d+%d" % (x, y))
            win._drag_root_x = x
            win._drag_root_y = y

    win.bind("<Button-1>", on_drag_start)
    win.bind("<B1-Motion>", on_drag_motion)

    def _save_pos(w, callback, oc):
        x, y = w.winfo_rootx(), w.winfo_rooty()
        callback(x, y)
        try:
            w.destroy()
        except Exception:
            logging.exception("Failed closing position picker after save.")
        _call_on_close_once()

    win.bind("<Destroy>", lambda e: _call_on_close_once(), add="+")
    return win
