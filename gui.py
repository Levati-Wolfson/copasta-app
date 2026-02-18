"""Main GUI: folder tree (Treeview), phrase list, add/edit phrase dialog, settings."""
import re
import logging
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import uuid
import ctypes

import data_model
from rich_editor import RichTextEditor


def _new_id():
    return str(uuid.uuid4())


def apply_dark_titlebar(window):
    """
    Apply Windows 10/11 dark mode to the native title bar.
    Uses DWM (Desktop Window Manager) API to set immersive dark mode.
    Fails gracefully on unsupported Windows versions or other OSs.
    """
    try:
        # Ensure window is fully initialized
        window.update_idletasks()
        
        # Get the window handle (HWND)
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        
        # DWMWA_USE_IMMERSIVE_DARK_MODE constants
        # 20 for Windows 11 and newer Windows 10 builds (build 19041+)
        # 19 for older Windows 10 builds
        DWMWA_USE_IMMERSIVE_DARK_MODE_NEW = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        
        # Value: 1 = dark mode, 0 = light mode
        use_dark_mode = ctypes.c_int(1)
        
        # Try newer attribute first (Windows 11 / Windows 10 build 19041+)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE_NEW,
                ctypes.byref(use_dark_mode),
                ctypes.sizeof(use_dark_mode)
            )
        except Exception:
            # Fall back to older attribute for older Windows 10 builds
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
                    ctypes.byref(use_dark_mode),
                    ctypes.sizeof(use_dark_mode)
                )
            except Exception:
                logging.exception("Failed to apply dark title bar with DWM attribute 19.")
    except Exception:
        # Gracefully handle any errors (unsupported OS, missing DLLs, etc.)
        logging.exception("Failed to apply dark title bar.")


def _center_toplevel_on_parent(toplevel, parent):
    toplevel.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    w = toplevel.winfo_width()
    h = toplevel.winfo_height()
    x = px + (pw - w) // 2
    y = py + (ph - h) // 2
    toplevel.geometry("+%d+%d" % (x, y))


def _ask_string_dialog(parent, title, prompt, initialvalue=""):
    """Dark-themed modal string input dialog."""
    result = {"value": None}
    d = tk.Toplevel(parent)
    d.title(title)
    d.transient(parent)
    d.grab_set()
    d.resizable(False, False)
    apply_dark_titlebar(d)

    frame = ttk.Frame(d, padding="10 10 10 10")
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text=prompt).pack(anchor=tk.W)
    value_var = tk.StringVar(value=initialvalue or "")
    entry = ttk.Entry(frame, textvariable=value_var, width=36)
    entry.pack(fill=tk.X, pady=(6, 10))
    entry.selection_range(0, tk.END)
    entry.focus_set()

    btns = ttk.Frame(frame)
    btns.pack(fill=tk.X)

    def on_ok():
        result["value"] = value_var.get()
        d.destroy()

    def on_cancel():
        result["value"] = None
        d.destroy()

    ttk.Button(btns, text="OK", command=on_ok, bootstyle="primary").pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btns, text="Cancel", command=on_cancel, bootstyle="secondary").pack(side=tk.LEFT)
    d.bind("<Return>", lambda _e: on_ok())
    d.bind("<Escape>", lambda _e: on_cancel())
    d.protocol("WM_DELETE_WINDOW", on_cancel)
    d.after(10, lambda: _center_toplevel_on_parent(d, parent))
    parent.wait_window(d)
    return result["value"]


def _ask_yesno_dialog(parent, title, message):
    """Dark-themed modal Yes/No confirmation dialog. Returns True for Yes, False for No."""
    result = {"value": False}
    d = tk.Toplevel(parent)
    d.title(title)
    d.transient(parent)
    d.grab_set()
    d.resizable(False, False)
    apply_dark_titlebar(d)

    frame = ttk.Frame(d, padding="16 16 16 12")
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text=message, wraplength=320).pack(anchor=tk.W, pady=(0, 16))

    btns = ttk.Frame(frame)
    btns.pack(fill=tk.X)

    def on_yes():
        result["value"] = True
        d.destroy()

    def on_no():
        result["value"] = False
        d.destroy()

    ttk.Button(btns, text="Yes", command=on_yes, bootstyle="danger").pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(btns, text="No", command=on_no, bootstyle="secondary").pack(side=tk.LEFT)
    d.bind("<Return>", lambda _e: on_yes())
    d.bind("<Escape>", lambda _e: on_no())
    d.protocol("WM_DELETE_WINDOW", on_no)
    d.after(10, lambda: _center_toplevel_on_parent(d, parent))
    parent.wait_window(d)
    return result["value"]


def _show_info_dialog(parent, title, message):
    """Dark-themed modal info dialog."""
    d = tk.Toplevel(parent)
    d.title(title)
    d.transient(parent)
    d.grab_set()
    d.resizable(False, False)
    apply_dark_titlebar(d)

    frame = ttk.Frame(d, padding="16 16 16 12")
    frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frame, text=message, wraplength=320).pack(anchor=tk.W, pady=(0, 16))
    ttk.Button(frame, text="OK", command=d.destroy, bootstyle="primary").pack(anchor=tk.W)
    d.bind("<Return>", lambda _e: d.destroy())
    d.bind("<Escape>", lambda _e: d.destroy())
    d.protocol("WM_DELETE_WINDOW", d.destroy)
    d.after(10, lambda: _center_toplevel_on_parent(d, parent))
    parent.wait_window(d)


def apply_theme(root, get_settings):
    """Apply modern dark theme using ttkbootstrap."""
    try:
        # ttkbootstrap theme is set on window creation, but we can adjust colors here if needed
        style = ttk.Style()
        # Additional manual styling for tk.Text widgets (not themed automatically)
        pass
    except Exception:
        logging.exception("Failed to apply theme.")


class PhraseDialog(tk.Toplevel):
    """Single Add/Edit phrase window: name, trigger type (Auto/Hotkey), and rich editor."""

    def __init__(
        self,
        parent,
        phrase_item=None,
        parent_folder_children=None,
        on_save=None,
        get_all_phrases_callback=None,
        require_new_abbreviation=False,
    ):
        """
        phrase_item: None for Add, or dict for Edit.
        parent_folder_children: list to append to (Add) or same list containing phrase (Edit).
        on_save: callable() after save.
        """
        super().__init__(parent)
        self._phrase = phrase_item
        self._parent_children = parent_folder_children
        self._on_save = on_save
        self._get_all_phrases = get_all_phrases_callback
        self._require_new_abbreviation = bool(require_new_abbreviation)
        self._clone_prompt_active = self._require_new_abbreviation and bool((phrase_item.get("trigger") or "").strip()) if phrase_item else False
        self._result = None

        self.title("Edit Phrase" if phrase_item else "Add Phrase")
        self.geometry("700x500")
        self.transient(parent)
        self.grab_set()
        
        # Apply dark title bar for Windows 10/11
        apply_dark_titlebar(self)

        config = data_model.load_config()
        last_trigger = config.get("last_trigger_type", "Auto")

        # Name
        top = ttk.Frame(self, padding="8 8 8 4")
        top.pack(fill=tk.X)
        ttk.Label(top, text="Phrase name / description:").pack(anchor=tk.W)
        self._name_var = tk.StringVar(value=(phrase_item.get("name") if phrase_item else ""))
        ttk.Entry(top, textvariable=self._name_var, width=60).pack(fill=tk.X, pady=(4, 8))

        # Trigger type
        trig_frame = ttk.Labelframe(self, text="Trigger", padding="8 4 8 8")
        trig_frame.pack(fill=tk.X, padx=8, pady=4)
        self._trigger_type = tk.StringVar(value=phrase_item.get("trigger_type") if phrase_item else last_trigger)
        ttk.Radiobutton(
            trig_frame,
            text="Auto (expand when you type the abbreviation)",
            variable=self._trigger_type,
            value="Auto",
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            trig_frame,
            text="Hotkey (expand when you press a key combo)",
            variable=self._trigger_type,
            value="Hotkey",
        ).pack(anchor=tk.W)
        ttk.Label(
            trig_frame,
            text="For both trigger types, use the abbreviation below.",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W)
        self._trigger_var = tk.StringVar(value=(phrase_item.get("trigger") if phrase_item else ""))
        ttk.Label(trig_frame, text="Abbreviation (trigger):").pack(anchor=tk.W)
        self._trigger_entry = ttk.Entry(trig_frame, textvariable=self._trigger_var, width=30)
        self._trigger_entry.pack(anchor=tk.W, pady=(0, 2))
        self._trigger_warning = ttk.Label(trig_frame, text="", bootstyle="danger")
        self._trigger_warning.pack(anchor=tk.W, pady=(0, 2))

        # Buttons at bottom so they're always visible
        btn_frame = ttk.Frame(self, padding="8 8 8 8")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._save_btn = ttk.Button(btn_frame, text="Save", command=self._save, bootstyle="success")
        self._save_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy, bootstyle="secondary").pack(side=tk.LEFT)

        # Rich text editor
        editor_frame = ttk.Labelframe(self, text="Content (rich text)", padding="8 4 8 8")
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._editor = RichTextEditor(editor_frame, height=10)
        self._editor.pack(fill=tk.BOTH, expand=True)
        if phrase_item and phrase_item.get("expansion_html"):
            self._editor.set_html(phrase_item.get("expansion_html"))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._trigger_var.trace_add("write", lambda *_: self._validate_trigger())
        self._validate_trigger()
        self.after(50, lambda: _center_toplevel_on_parent(self, parent))

    def _is_duplicate_trigger(self, value):
        if not value:
            return False
        if not self._get_all_phrases:
            return False
        current_id = self._phrase.get("id") if self._phrase else None
        for p in self._get_all_phrases() or []:
            if current_id and p.get("id") == current_id:
                continue
            if (p.get("trigger") or "").strip() == value:
                return True
        return False

    def _validate_trigger(self):
        trigger = self._trigger_var.get().strip()
        message = ""
        if self._clone_prompt_active:
            if trigger:
                self._clone_prompt_active = False
            else:
                message = "change the abbreviation or clear it to save without one"
        if not message and trigger:
            if any(ch.isspace() for ch in trigger):
                message = "No spaces, tabs, or line breaks allowed"
            elif self._is_duplicate_trigger(trigger):
                message = "Must be different from other phrases"
        self._trigger_warning.config(text=message)
        self._save_btn.config(state=(tk.NORMAL if not message else tk.DISABLED))
        return not message

    def _save(self):
        if not self._validate_trigger():
            return
        name = self._name_var.get().strip()
        trigger_type = self._trigger_type.get()
        trigger = self._trigger_var.get().strip()
        expansion_html = self._editor.get_html()
        # Persist last trigger type
        config = data_model.load_config()
        config["last_trigger_type"] = trigger_type
        data_model.save_config(config)

        if self._phrase:
            self._phrase["name"] = name
            self._phrase["trigger_type"] = trigger_type
            self._phrase["trigger"] = trigger
            self._phrase["expansion_html"] = expansion_html
        else:
            new_phrase = {
                "type": "phrase",
                "id": _new_id(),
                "name": name,
                "trigger": trigger,
                "trigger_type": trigger_type,
                "expansion_html": expansion_html,
            }
            self._parent_children.append(new_phrase)
        if self._on_save:
            self._on_save()
        self._result = True
        self.destroy()

    def destroy(self):
        self.grab_release()
        super().destroy()


class MainWindow:
    """Main app window: left Treeview (folders/phrases), toolbar, right panel / add-edit."""

    def __init__(self, get_data, save_data, get_settings=None, save_settings=None, on_close_callback=None, on_settings_callback=None):
        self._get_data = get_data
        self._save_data = save_data
        self._get_settings = get_settings
        self._save_settings = save_settings
        self._on_close = on_close_callback
        self._on_settings = on_settings_callback

        # Use ttkbootstrap Window with modern dark theme
        self.root = ttk.Window(themename="darkly")
        self.root.title("Copasta")
        self.root.minsize(500, 400)
        self.root.geometry(self._load_geometry())
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._build_ui()
        self._refresh_tree()
        
        # Apply dark title bar for Windows 10/11
        apply_dark_titlebar(self.root)

    def _build_ui(self):
        # Custom ttk menu bar (replaces native menu for dark theme consistency)
        menu_frame = ttk.Frame(self.root)
        menu_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 0))
        
        # File menu
        file_menubutton = ttk.Menubutton(menu_frame, text="File")
        file_menubutton.pack(side=tk.LEFT, padx=2)
        file_menu = tk.Menu(
            file_menubutton,
            tearoff=0,
            bg="#2b2b2b",
            fg="#ffffff",
            activebackground="#375a7f",
            activeforeground="#ffffff",
            borderwidth=0,
            relief=tk.FLAT
        )
        file_menu.add_command(label="Settings...", command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_window_close)
        file_menubutton.config(menu=file_menu)
        
        if self._on_settings:
            self._settings_cmd = self._open_settings
        else:
            self._settings_cmd = None

        # Paned: left tree, right content (with visible sash/separator)
        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left: tree + buttons (buttons can wrap to two rows when narrow)
        left = ttk.Frame(paned, width=280)
        paned.add(left, weight=0)
        left.pack_propagate(False)  # Prevent frame from shrinking below width
        ttk.Label(left, text="Folders & Phrases", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        # Button area at bottom so it always gets full height (not cut off)
        btn_container = ttk.Frame(left)
        btn_container.pack(side=tk.BOTTOM, fill=tk.X, pady=4)
        btn_row1 = ttk.Frame(btn_container)
        btn_row1.pack(fill=tk.X)
        btn_row2 = ttk.Frame(btn_container)
        btn_row2.pack(fill=tk.X, pady=(2, 0))
        ttk.Button(btn_row1, text="New Folder", command=self._new_folder, bootstyle="info").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row1, text="Rename", command=self._rename, bootstyle="warning").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row1, text="Delete", command=self._delete, bootstyle="danger").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row2, text="Add Phrase", command=self._add_phrase, bootstyle="success").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row2, text="Edit Phrase", command=self._edit_phrase, bootstyle="primary").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row2, text="Clone Phrase", command=self._clone_phrase, bootstyle="secondary").pack(side=tk.LEFT)
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        self._tree = ttk.Treeview(tree_frame, show="tree", height=18, selectmode="browse")
        tree_scroll = ttk.Scrollbar(tree_frame)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.config(yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self._tree.yview)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_tree_double)
        self._tree.bind("<Delete>", lambda e: self._delete())
        self._tree.tag_configure("folder", font=("Segoe UI", 10, "bold"))
        self._tree.tag_configure("phrase", font=("Segoe UI", 10))
        self._setup_drag_drop()

        # Right: phrase preview (manually styled for dark mode)
        right = ttk.Frame(paned, padding="8 0 0 0")
        paned.add(right, weight=1)
        self._right_label = ttk.Label(right, text="Select a folder or phrase, or use Add Phrase.", font=("Segoe UI", 10, "bold"))
        self._right_label.pack(anchor=tk.W)
        self._preview_sep = ttk.Separator(right, orient=tk.HORIZONTAL)
        self._preview_sep.pack(fill=tk.X, pady=(2, 4))
        self._preview_abbr_label = ttk.Label(right, text="")
        self._preview_abbr_label.pack(anchor=tk.W, pady=(0, 2))
        self._preview_editor = RichTextEditor(right, height=20, show_toolbar=False, readonly=True)
        self._preview_editor.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    def _refresh_tree(self):
        # Preserve which folders were expanded (tree iids = our item ids)
        expanded_iids = set()
        def collect_expanded(parent_iid):
            for iid in self._tree.get_children(parent_iid):
                try:
                    if self._tree.item(iid, "open"):
                        expanded_iids.add(iid)
                except tk.TclError:
                    pass
                collect_expanded(iid)
        collect_expanded("")
        for item in self._tree.get_children():
            self._tree.delete(item)
        data = self._get_data()
        for item in data.get("children", []):
            self._insert_item("", item)
        for iid in expanded_iids:
            try:
                self._tree.item(iid, open=True)
            except tk.TclError:
                pass

    def _insert_item(self, parent_iid, item):
        item_id = item.get("id")
        if item.get("type") == "folder":
            name = item.get("name") or "New Folder"
            iid = self._tree.insert(parent_iid, tk.END, iid=item_id, text="\U0001f4c1 " + name, tags=("folder",))
            for child in item.get("children", []):
                self._insert_item(iid, child)
        else:
            name = item.get("name") or "(no name)"
            iid = self._tree.insert(parent_iid, tk.END, iid=item_id, text="\U0001f4c4 " + name, tags=("phrase",))

    def _setup_drag_drop(self):
        self._drag_iid = None
        self._drop_target_iid = None
        self._drop_mode = None  # "into" | "before" | "after"
        self._tree.tag_configure("drop_target_into", background="#cce0ff")
        # Thin line shown between items when dropping "between" (no row highlight)
        self._drop_line = tk.Frame(self._tree.master, height=2, bg="#2a7fff", highlightthickness=0)
        self._tree.bind("<ButtonPress-1>", self._on_drag_start)
        self._tree.bind("<B1-Motion>", self._on_drag_motion)
        self._tree.bind("<ButtonRelease-1>", self._on_drag_end)
        self._tree.bind("<Leave>", self._on_drag_leave)

    def _clear_drop_indicator(self):
        if self._drop_target_iid:
            try:
                current = self._tree.item(self._drop_target_iid, "tags")
                drop_tags = ("drop_target", "drop_target_into", "drop_target_between")
                self._tree.item(self._drop_target_iid, tags=tuple(t for t in current if t not in drop_tags))
            except Exception:
                logging.exception("Failed clearing drag-drop tree tag indicator.")
            self._drop_target_iid = None
            self._drop_mode = None
        try:
            self._drop_line.place_forget()
        except Exception:
            logging.exception("Failed hiding drag-drop insertion line.")

    def _tree_coords(self, event):
        """Return (x, y) relative to the tree widget (handles scroll/focus)."""
        try:
            rx, ry = self._tree.winfo_pointerxy()
            return (rx - self._tree.winfo_rootx(), ry - self._tree.winfo_rooty())
        except Exception:
            return (event.x, event.y)

    def _get_drop_position(self, event):
        """Return (drop_iid, mode) where mode is 'into' | 'before' | 'after', or (None, None)."""
        tx, ty = self._tree_coords(event)
        drop_iid = self._tree.identify_row(ty)
        if not drop_iid or drop_iid == self._drag_iid:
            return None, None
        bbox = self._tree.bbox(drop_iid)
        if not bbox:
            return drop_iid, "after"
        x, y, w, h = bbox
        mid = y + h // 2
        in_top_half = ty < mid
        data = self._get_data()
        tgt_item, tgt_list, _ = self._find_item_by_iid(data.get("children", []), "", drop_iid)
        if not tgt_item:
            return None, None
        if in_top_half:
            return drop_iid, "before"
        if tgt_item.get("type") == "folder":
            return drop_iid, "into"
        return drop_iid, "after"

    def _on_drag_start(self, event):
        _, ty = self._tree_coords(event)
        self._drag_iid = self._tree.identify_row(ty)
        if not self._drag_iid:
            self._drag_iid = None

    def _on_drag_motion(self, event):
        if self._drag_iid is None:
            return
        drop_iid, mode = self._get_drop_position(event)
        self._clear_drop_indicator()
        if drop_iid and mode:
            try:
                self._drop_target_iid = drop_iid
                self._drop_mode = mode
                if mode == "into":
                    current = self._tree.item(drop_iid, "tags")
                    drop_tags = ("drop_target", "drop_target_into", "drop_target_between")
                    cleaned = tuple(t for t in current if t not in drop_tags)
                    self._tree.item(drop_iid, tags=cleaned + ("drop_target_into",))
                else:
                    # Show insertion line between items (no row highlight)
                    bbox = self._tree.bbox(drop_iid)
                    if bbox:
                        x, y, w, h = bbox
                        line_y = y if mode == "before" else y + h
                        # Position line in tree's parent; y relative to tree + tree's offset
                        ty = self._tree.winfo_y()
                        self._drop_line.place(
                            in_=self._tree.master,
                            x=self._tree.winfo_x(),
                            y=ty + line_y - 1,
                            width=self._tree.winfo_width(),
                            height=2,
                        )
            except Exception:
                logging.exception("Failed updating drag-drop visual indicator.")

    def _on_drag_leave(self, event):
        self._clear_drop_indicator()

    def _on_drag_end(self, event):
        if self._drag_iid is None:
            return
        drop_iid, mode = self._get_drop_position(event)
        # Prefer the mode we showed during motion (so "between" isn't lost on slight move)
        if drop_iid and self._drop_target_iid == drop_iid and self._drop_mode:
            mode = self._drop_mode
        self._clear_drop_indicator()
        if not drop_iid or not mode:
            self._drag_iid = None
            return
        data = self._get_data()
        src_item, src_list, _ = self._find_item_by_iid(data.get("children", []), "", self._drag_iid)
        tgt_item, tgt_list, _ = self._find_item_by_iid(data.get("children", []), "", drop_iid)
        if not src_item or not tgt_item:
            self._drag_iid = None
            return
        if mode == "into":
            src_list.remove(src_item)
            tgt_item.setdefault("children", []).append(src_item)
        else:
            src_list.remove(src_item)
            insert_at = tgt_list.index(tgt_item)
            if mode == "after":
                insert_at += 1
            tgt_list.insert(insert_at, src_item)
        self._save_data(self._get_data())
        self._refresh_tree()
        self._tree.selection_set(src_item.get("id"))
        self._drag_iid = None

    def _get_selected_item_and_parent(self):
        sel = self._tree.selection()
        if not sel:
            return None, None, None
        iid = sel[0]
        data = self._get_data()
        return self._find_item_by_iid(data.get("children", []), "", iid)

    def _find_item_by_iid(self, children, parent_iid, target_iid):
        # target_iid is the item's ID (used as tree iid)
        for item in children:
            if item.get("id") == target_iid:
                return item, children, None
            if item.get("type") == "folder":
                found, lst, par = self._find_item_by_iid(item.get("children", []), item.get("id"), target_iid)
                if found is not None:
                    return found, lst, par if par is not None else item
        return None, None, None

    def _on_tree_select(self, event):
        item, _, _ = self._get_selected_item_and_parent()
        if item and item.get("type") == "phrase":
            html = item.get("expansion_html") or ""
            trig = (item.get("trigger") or "").strip()
            trig_type = (item.get("trigger_type") or "Auto").lower()
            self._right_label.config(text="Phrase Preview")
            self._preview_abbr_label.config(text="Abbreviation: %s     (%s)" % (trig, trig_type))
            self._preview_editor.set_html(html)
        else:
            self._preview_editor.set_html("")
            self._preview_abbr_label.config(text="")
            self._right_label.config(text="Select a folder or phrase, or use Add Phrase.")

    def _on_tree_double(self, event):
        item, _, _ = self._get_selected_item_and_parent()
        if item and item.get("type") == "phrase":
            self._edit_phrase()

    def _get_current_folder_children(self):
        """Return (list to add to, parent folder or None for root). If a folder is selected, return its children (so we add inside it)."""
        sel = self._tree.selection()
        if not sel:
            data = self._get_data()
            return data.get("children", []), None
        iid = sel[0]
        data = self._get_data()
        item, children, _ = self._find_item_by_iid(data.get("children", []), "", iid)
        if not item:
            return data.get("children", []), None
        if item.get("type") == "folder":
            return item.get("children", []), item
        parent_iid = self._tree.parent(iid)
        if parent_iid == "":
            return data.get("children", []), None
        parent_item, _, _ = self._find_item_by_iid(data.get("children", []), "", parent_iid)
        if not parent_item:
            return data.get("children", []), None
        return parent_item.get("children", []), parent_item

    def _new_folder(self):
        children, _ = self._get_current_folder_children()
        name = _ask_string_dialog(self.root, "New Folder", "Folder name:", initialvalue="New Folder")
        if not name:
            return
        folder = {
            "type": "folder",
            "id": _new_id(),
            "name": name.strip(),
            "children": [],
        }
        children.append(folder)
        self._save_data(self._get_data())
        self._refresh_tree()

    def _rename(self):
        item, children, _ = self._get_selected_item_and_parent()
        if not item:
            _show_info_dialog(self.root, "Rename", "Select a folder or phrase first.")
            return
        current = item.get("name") or ""
        name = _ask_string_dialog(self.root, "Rename", "New name:", initialvalue=current)
        if name is not None and name.strip():
            item["name"] = name.strip()
            self._save_data(self._get_data())
            self._refresh_tree()

    def _delete(self):
        item, children, _ = self._get_selected_item_and_parent()
        if not item:
            _show_info_dialog(self.root, "Delete", "Select a folder or phrase first.")
            return
        name = item.get("name") or "this item"
        if not _ask_yesno_dialog(self.root, "Delete", "Delete \u2018%s\u2019?" % name):
            return
        children.remove(item)
        self._save_data(self._get_data())
        self._refresh_tree()

    def _add_phrase(self):
        children, _ = self._get_current_folder_children()
        d = PhraseDialog(
            self.root,
            phrase_item=None,
            parent_folder_children=children,
            on_save=lambda: self._save_and_refresh(),
            get_all_phrases_callback=lambda: data_model.collect_all_phrases(self._get_data().get("children", [])),
        )
        self._wait_dialog(d)

    def _edit_phrase(self):
        item, children, _ = self._get_selected_item_and_parent()
        if not item or item.get("type") != "phrase":
            _show_info_dialog(self.root, "Edit", "Select a phrase first.")
            return
        d = PhraseDialog(
            self.root,
            phrase_item=item,
            parent_folder_children=children,
            on_save=lambda: self._save_and_refresh(),
            get_all_phrases_callback=lambda: data_model.collect_all_phrases(self._get_data().get("children", [])),
        )
        self._wait_dialog(d)

    def _clone_phrase(self):
        item, children, _ = self._get_selected_item_and_parent()
        if not item or item.get("type") != "phrase":
            _show_info_dialog(self.root, "Clone", "Select a phrase first.")
            return
        clone = {
            "type": "phrase",
            "id": _new_id(),
            "name": "Copy of " + (item.get("name") or "phrase"),
            "trigger": "",
            "trigger_type": item.get("trigger_type", "Auto"),
            "expansion_html": item.get("expansion_html") or "",
        }
        children.append(clone)
        d = PhraseDialog(
            self.root,
            phrase_item=clone,
            parent_folder_children=children,
            on_save=lambda: self._save_and_refresh(),
            get_all_phrases_callback=lambda: data_model.collect_all_phrases(self._get_data().get("children", [])),
            require_new_abbreviation=True,
        )
        self._wait_dialog(d)
        if not getattr(d, "_result", False):
            try:
                children.remove(clone)
            except ValueError:
                pass
            return
        self._tree.selection_set(clone.get("id"))

    def _save_and_refresh(self):
        self._save_data(self._get_data())
        self._refresh_tree()
        if hasattr(self, "_on_phrase_save"):
            self._on_phrase_save()

    def _wait_dialog(self, d):
        self.root.wait_window(d)

    def _open_settings(self):
        if self._on_settings:
            self._on_settings()

    def set_phrase_save_callback(self, cb):
        self._on_phrase_save = cb

    def _load_geometry(self):
        if self._get_settings:
            geom = self._get_settings().get("window_geometry", "750x500")
            if geom and re.match(r"^\d+x\d+(\+[-\d]+\+[-\d]+)?$", geom):
                return geom
        return "750x500"

    def _save_geometry(self):
        if self._get_settings and self._save_settings:
            try:
                geom = self.root.geometry()
                s = self._get_settings()
                s["window_geometry"] = geom
                self._save_settings(s)
            except Exception:
                logging.exception("Failed saving window geometry.")

    def _on_window_close(self):
        self._save_geometry()
        if self._on_close:
            self._on_close()
        else:
            self.root.destroy()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self._save_geometry()
        self.root.withdraw()

    def destroy(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class SettingsDialog(tk.Toplevel):
    """Settings: floating menu hotkey, position, Start with Windows, Dark mode."""

    def __init__(self, parent, get_settings, save_settings, on_position_picker=None):
        super().__init__(parent)

        # Step 1: hide immediately before OS gets a chance to render anything.
        self.withdraw()

        self._get_settings = get_settings
        self._save_settings = save_settings
        self._on_position_picker = on_position_picker
        self._parent = parent
        self.title("Settings")
        self.transient(parent)

        # Step 2: build all widgets while window is hidden.
        s = get_settings()
        ttk.Label(self, text="Floating phrase menu").pack(anchor=tk.W, padx=8, pady=(8, 4))
        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(row1, text="Phrase window hotkey:").pack(side=tk.LEFT, padx=(0, 8))
        self._hotkey_var = tk.StringVar(value=s.get("floating_menu_hotkey", "ctrl+shift+space"))
        self._hotkey_entry = ttk.Entry(row1, textvariable=self._hotkey_var, width=25)
        self._hotkey_entry.pack(side=tk.LEFT, padx=(0, 8))
        self._record_btn = ttk.Button(row1, text="Record", command=self._record_hotkey)
        self._record_btn.pack(side=tk.LEFT)
        self._save_hotkey_btn = ttk.Button(row1, text="Save", command=self._save_recorded_hotkey)
        self._pending_hotkey = None

        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(row2, text="Expansion hotkey:").pack(side=tk.LEFT, padx=(0, 8))
        self._expansion_hotkey_var = tk.StringVar(value=s.get("expansion_hotkey", "ctrl+alt+e"))
        ttk.Entry(row2, textvariable=self._expansion_hotkey_var, width=25).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(row2, text="(For phrases with hotkey trigger)", font=("Segoe UI", 8)).pack(side=tk.LEFT)

        ttk.Label(self, text="Popup position").pack(anchor=tk.W, padx=8, pady=(12, 4))
        self._pos_var = tk.StringVar(value=s.get("floating_menu_position", "cursor"))
        ttk.Radiobutton(self, text="At text cursor location", variable=self._pos_var, value="cursor").pack(anchor=tk.W, padx=8)
        ttk.Radiobutton(self, text="At mouse cursor location", variable=self._pos_var, value="mouse").pack(anchor=tk.W, padx=8)
        ttk.Radiobutton(self, text="Fixed custom position", variable=self._pos_var, value="fixed").pack(anchor=tk.W, padx=8)
        ttk.Button(self, text="Drag window to set position...", command=self._open_position_picker).pack(anchor=tk.W, padx=8, pady=4)

        try:
            import startup
            self._start_var = tk.BooleanVar(value=s.get("start_with_windows", False))
            ttk.Checkbutton(self, text="Start when Windows starts", variable=self._start_var).pack(anchor=tk.W, padx=8, pady=(12, 0))
        except Exception:
            self._start_var = None

        btn_frame = ttk.Frame(self, padding="8 16 8 8")
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="OK", command=self._ok, bootstyle="success").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy, bootstyle="secondary").pack(side=tk.LEFT)
        self._on_ok_callback = None

        # Step 3: force geometry manager to calculate sizes while still hidden.
        self.update_idletasks()

        # Step 4: compute final centered position and apply.
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        except Exception:
            x, y = 100, 100
        self.geometry("+%d+%d" % (x, y))

        # Step 5: apply dark title bar while still hidden.
        apply_dark_titlebar(self)

        # Step 6: reveal in final position — no flash, no movement.
        self.deiconify()

    def set_on_ok(self, cb):
        self._on_ok_callback = cb

    def _open_position_picker(self):
        self._pos_var.set("fixed")
        if self._on_position_picker:
            self._on_position_picker(self)

    def _record_hotkey(self):
        import keyboard
        # Ensure an older recorder hook is not still active.
        if getattr(self, "_hotkey_hook", None):
            try:
                self._hotkey_hook()
            except Exception:
                logging.exception("Failed removing existing settings hotkey hook.")
            self._hotkey_hook = None
        self._hotkey_var.set("(press key combo...)")
        self._recording = [True]
        self._pending_hotkey = None
        self._active_modifiers = set()
        try:
            self._save_hotkey_btn.pack_forget()
        except Exception:
            logging.exception("Failed to hide hotkey save button before recording.")

        def norm(name):
            n = (name or "").strip().lower()
            aliases = {
                "left ctrl": "ctrl",
                "right ctrl": "ctrl",
                "control": "ctrl",
                "left shift": "shift",
                "right shift": "shift",
                "skift": "shift",
                "vänster skift": "shift",
                "hoger skift": "shift",
                "höger skift": "shift",
                "left alt": "alt",
                "right alt": "alt",
                "alt gr": "alt",
                "altgr": "alt",
                "left windows": "win",
                "right windows": "win",
                "windows": "win",
            }
            return aliases.get(n, n)

        def is_modifier_like(name, scan_code=None):
            n = (name or "").strip().lower()
            # Layout-independent fallback: common modifier scan codes.
            # Shift: 42/54, Ctrl: 29/3613, Alt: 56/3640, Win: 3675/3676
            if scan_code in (42, 54, 29, 3613, 56, 3640, 3675, 3676):
                return True
            if n in ("ctrl", "shift", "alt", "win"):
                return True
            # Catch localized/variant names such as shift_l, right shift, etc.
            return any(token in n for token in ("shift", "skift", "ctrl", "control", "alt", "win", "windows"))

        def safe_pressed(name):
            try:
                return keyboard.is_pressed(name)
            except Exception:
                return False

        def on_key(e):
            if not self._recording[0]:
                return
            try:
                key_name = norm(getattr(e, "name", ""))
                scan_code = getattr(e, "scan_code", None)
                if not key_name:
                    return
                event_type = getattr(e, "event_type", "down")
                if event_type == "up":
                    if is_modifier_like(key_name, scan_code):
                        if "ctrl" in key_name or "control" in key_name:
                            self._active_modifiers.discard("ctrl")
                        if "shift" in key_name or "skift" in key_name:
                            self._active_modifiers.discard("shift")
                        if "alt" in key_name:
                            self._active_modifiers.discard("alt")
                        if "win" in key_name or "windows" in key_name:
                            self._active_modifiers.discard("win")
                    return
                if is_modifier_like(key_name, scan_code):
                    if "ctrl" in key_name or "control" in key_name:
                        self._active_modifiers.add("ctrl")
                    if "shift" in key_name or "skift" in key_name:
                        self._active_modifiers.add("shift")
                    if "alt" in key_name:
                        self._active_modifiers.add("alt")
                    if "win" in key_name or "windows" in key_name:
                        self._active_modifiers.add("win")
                    return
                parts = []
                if (
                    "ctrl" in self._active_modifiers
                    or safe_pressed("ctrl")
                    or safe_pressed("left ctrl")
                    or safe_pressed("right ctrl")
                    or safe_pressed("control")
                ):
                    parts.append("ctrl")
                if (
                    "shift" in self._active_modifiers
                    or safe_pressed("shift")
                    or safe_pressed("left shift")
                    or safe_pressed("right shift")
                ):
                    parts.append("shift")
                if (
                    "alt" in self._active_modifiers
                    or safe_pressed("alt")
                    or safe_pressed("left alt")
                    or safe_pressed("right alt")
                    or safe_pressed("alt gr")
                    or safe_pressed("altgr")
                ):
                    parts.append("alt")
                if (
                    "win" in self._active_modifiers
                    or safe_pressed("windows")
                    or safe_pressed("left windows")
                    or safe_pressed("right windows")
                    or safe_pressed("win")
                ):
                    parts.append("win")
                parts.append(key_name)
                # Deduplicate while keeping order (avoid results like "shift+shift")
                combo = "+".join(dict.fromkeys(p for p in parts if p))
                remover = getattr(self, "_hotkey_hook", None)
                self._recording[0] = False
                self.after(0, lambda: self._apply_recorded_hotkey(combo, remover))
            except Exception:
                logging.exception("Settings hotkey record handler failed.")

        self._hotkey_hook = keyboard.on_press(on_key)
        # No timeout: keep listening until combo captured or dialog closes.

    def _apply_recorded_hotkey(self, combo, remover):
        self._pending_hotkey = combo
        self._hotkey_var.set(combo)
        self._save_hotkey_btn.pack(side=tk.LEFT, padx=(6, 0))
        if remover:
            try:
                remover()
            except Exception:
                logging.exception("Failed to remove settings dialog hotkey hook.")
            self._hotkey_hook = None

    def _save_recorded_hotkey(self):
        if self._pending_hotkey:
            self._hotkey_var.set(self._pending_hotkey)
        # Persist immediately from this Save button
        s = self._get_settings()
        s["floating_menu_hotkey"] = self._hotkey_var.get().strip() or "ctrl+shift+space"
        self._save_settings(s)
        if getattr(self, "_on_ok_callback", None):
            self._on_ok_callback()
        self._pending_hotkey = None
        self._save_hotkey_btn.pack_forget()

    def _stop_hotkey_record(self, previous_value=None):
        if getattr(self, "_hotkey_hook", None):
            try:
                self._hotkey_hook()
            except Exception:
                logging.exception("Failed stopping settings hotkey recording hook.")
            self._hotkey_hook = None
        if getattr(self, "_recording", [False])[0]:
            self._recording[0] = False
            if previous_value:
                self._hotkey_var.set(previous_value)
        self._pending_hotkey = None

    def _ok(self):
        s = self._get_settings()
        s["floating_menu_hotkey"] = self._hotkey_var.get().strip() or "ctrl+shift+space"
        s["expansion_hotkey"] = self._expansion_hotkey_var.get().strip() or "ctrl+alt+e"
        s["floating_menu_position"] = self._pos_var.get()
        if self._start_var is not None:
            s["start_with_windows"] = self._start_var.get()
            try:
                import startup
                startup.set_start_with_windows(s["start_with_windows"])
            except Exception:
                logging.exception("Failed to update startup-with-Windows setting.")
        self._save_settings(s)
        if getattr(self, "_on_ok_callback", None):
            self._on_ok_callback()
        self.destroy()

    def destroy(self):
        self._stop_hotkey_record(self._hotkey_var.get().strip())
        super().destroy()
