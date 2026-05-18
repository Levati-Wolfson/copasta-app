"""Main GUI: folder tree (Treeview), phrase list, add/edit phrase dialog, settings."""
import copy
import json
import logging
import os
import re
import subprocess
import tkinter as tk
from tkinter import filedialog
import tkinter.font as tkFont
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import uuid
import ctypes

import app_icon
import data_model
from rich_editor import RichTextEditor


def _new_id():
    return str(uuid.uuid4())


def _downloads_folder():
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def _sanitize_export_filename_part(name):
    """Strip characters illegal in Windows filenames; keep it reasonably short."""
    s = (name or "").strip() or "phrase"
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = s.strip(" .") or "phrase"
    return s[:80]


def _parse_import_file(path):
    """
    Load export JSON. Returns either:
    - {"mode": "tree", "items": [...]}  (v2: folders + phrases, nested)
    - {"mode": "flat", "phrases": [...]}  (legacy: phrase list only)
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            if len(items) > 0:
                for i, it in enumerate(items):
                    if not isinstance(it, dict) or it.get("type") not in ("folder", "phrase"):
                        raise ValueError("Invalid entry at index %d in items (expected folder or phrase)." % i)
                return {"mode": "tree", "items": items}
            # empty items array — fall through and try legacy "phrases" etc.
        if "phrases" in data:
            raw = data["phrases"]
        elif data.get("type") == "phrase":
            raw = [data]
        else:
            raise ValueError("This file does not look like a Copasta export (expected items or phrases).")
    elif isinstance(data, list):
        if not data:
            raise ValueError("Empty list in file.")
        if all(isinstance(x, dict) and x.get("type") == "phrase" for x in data):
            raw = data
        elif all(isinstance(x, dict) and x.get("type") in ("folder", "phrase") for x in data):
            return {"mode": "tree", "items": data}
        else:
            raise ValueError("Unrecognized list format in file.")
    else:
        raise ValueError("Unrecognized JSON structure.")
    if not isinstance(raw, list):
        raise ValueError("Invalid phrases list in file.")
    out = []
    for x in raw:
        if isinstance(x, dict) and x.get("type") == "phrase":
            out.append(x)
    if not out:
        raise ValueError("No phrases found in this file.")
    return {"mode": "flat", "phrases": out}


def _clone_tree_new_ids(node):
    """Deep clone a folder/phrase subtree with fresh UUIDs on every node."""
    n = copy.deepcopy(node)
    n["id"] = _new_id()
    if n.get("type") == "folder":
        data_model._ensure_folder(n)
        n["children"] = [_clone_tree_new_ids(ch) for ch in (n.get("children") or [])]
        return n
    data_model._ensure_phrase(n)
    return n


def _open_explorer_select(path):
    """Windows: open a folder window with the given file selected.

    Path must be passed as its own argv after ``/select,`` — if it is concatenated
    onto ``/select,``, paths with spaces get one big quoted token and Explorer
    mis-parses it (often opening Documents instead of the exe folder).
    """
    path = os.path.normpath(os.path.abspath(path))
    if not os.path.isfile(path):
        return
    try:
        subprocess.run(
            ["explorer", "/select,", path],
            check=False,
            shell=False,
        )
    except Exception:
        logging.exception("Failed to open Explorer for exported file.")


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


class PhraseDialog(tk.Toplevel):
    """Single Add/Edit phrase window: name, abbreviation, and rich editor."""

    def __init__(
        self,
        parent,
        phrase_item=None,
        parent_folder_children=None,
        on_save=None,
        get_all_phrases_callback=None,
        require_new_abbreviation=False,
        font_size_offset=0,
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

        # Name
        top = ttk.Frame(self, padding="8 8 8 4")
        top.pack(fill=tk.X)
        ttk.Label(top, text="Phrase name / description:").pack(anchor=tk.W)
        self._name_var = tk.StringVar(value=(phrase_item.get("name") if phrase_item else ""))
        self._name_entry = ttk.Entry(top, textvariable=self._name_var, width=60)
        self._name_entry.pack(fill=tk.X, pady=(4, 8))

        # Abbreviation
        trig_frame = ttk.Labelframe(self, text="Abbreviation", padding="8 4 8 8")
        trig_frame.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(
            trig_frame,
            text="Type this to auto-expand the phrase (leave empty to paste from the overlay only).",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W)
        self._trigger_var = tk.StringVar(value=(phrase_item.get("trigger") if phrase_item else ""))
        self._trigger_entry = ttk.Entry(trig_frame, textvariable=self._trigger_var, width=30)
        self._trigger_entry.pack(anchor=tk.W, pady=(4, 2))
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
        self._editor = RichTextEditor(editor_frame, height=10, font_size_offset=font_size_offset)
        self._editor.pack(fill=tk.BOTH, expand=True)
        if phrase_item and phrase_item.get("expansion_html"):
            self._editor.set_html(phrase_item.get("expansion_html"))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._trigger_var.trace_add("write", lambda *_: self._validate_trigger())
        self._validate_trigger()
        self.after(50, lambda: _center_toplevel_on_parent(self, parent))
        if not phrase_item:
            self.after(60, lambda: (self._name_entry.focus_set(), self._name_entry.selection_range(0, tk.END)))

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
        trigger = self._trigger_var.get().strip()
        expansion_html = self._editor.get_html()

        if self._phrase:
            self._phrase["name"] = name
            self._phrase["trigger_type"] = "Auto"
            self._phrase["trigger"] = trigger
            self._phrase["expansion_html"] = expansion_html
        else:
            new_phrase = {
                "type": "phrase",
                "id": _new_id(),
                "name": name,
                "trigger": trigger,
                "trigger_type": "Auto",
                "expansion_html": expansion_html,
            }
            self._parent_children.append(new_phrase)
            self._phrase = new_phrase
        if self._on_save:
            self._on_save()
        self._result = True
        self.destroy()

    def destroy(self):
        self.grab_release()
        super().destroy()


class MainWindow:
    """Main app window: left Treeview (folders/phrases), toolbar, right panel / add-edit."""

    def __init__(self, get_data, save_data, get_settings=None, save_settings=None, on_close_callback=None, on_settings_callback=None, on_quit_callback=None, on_check_for_updates_callback=None, app_version=None):
        self._get_data = get_data
        self._save_data = save_data
        self._get_settings = get_settings
        self._save_settings = save_settings
        self._on_close = on_close_callback
        self._on_settings = on_settings_callback
        self._on_quit = on_quit_callback
        self._on_check_for_updates = on_check_for_updates_callback
        self._app_version = app_version
        self._dup_ab_phrase_ids = set()
        self._dup_ab_folder_ids = set()

        # Use ttkbootstrap Window with modern dark theme
        self.root = ttk.Window(themename="darkly")
        self.root.title("Copasta")
        self.root.minsize(500, 400)
        self.root.geometry(self._load_geometry())
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        app_icon.apply_window_icon(self.root)

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
        self._file_menubutton = file_menubutton
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
        file_menu.add_command(label="Minimize to tray", command=self._on_window_close)
        file_menu.add_command(label="Quit", command=self._quit)
        file_menubutton.config(menu=file_menu)

        # Help menu
        help_menubutton = ttk.Menubutton(menu_frame, text="Help")
        help_menubutton.pack(side=tk.LEFT, padx=2)
        help_menu = tk.Menu(
            help_menubutton,
            tearoff=0,
            bg="#2b2b2b",
            fg="#ffffff",
            activebackground="#375a7f",
            activeforeground="#ffffff",
            borderwidth=0,
            relief=tk.FLAT,
        )
        if self._on_check_for_updates is not None:
            help_menu.add_command(label="Check for updates...", command=self._on_check_for_updates)
            help_menu.add_separator()
        help_menu.add_command(label="About Copasta", command=self._show_about)
        help_menubutton.config(menu=help_menu)

        self._dup_banner = ttk.Label(
            menu_frame,
            text="",
            bootstyle="danger",
            wraplength=520,
            justify=tk.LEFT,
        )
        
        # Paned: left tree, right content (with visible sash/separator)
        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left: tree + buttons (buttons can wrap to two rows when narrow)
        left = ttk.Frame(paned, width=280)
        self._left_frame = left
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
        btn_row3 = ttk.Frame(btn_container)
        btn_row3.pack(fill=tk.X, pady=(2, 0))
        ttk.Button(btn_row1, text="New Folder", command=self._new_folder, bootstyle="info").pack(side=tk.LEFT, padx=(0, 4))
        self._rename_btn = ttk.Button(btn_row1, text="Rename", command=self._rename, bootstyle="warning")
        self._rename_btn.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row1, text="Delete", command=self._delete, bootstyle="danger").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row2, text="Add Phrase", command=self._add_phrase, bootstyle="success").pack(side=tk.LEFT, padx=(0, 4))
        self._edit_btn = ttk.Button(btn_row2, text="Edit Phrase", command=self._edit_phrase, bootstyle="primary")
        self._edit_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._clone_btn = ttk.Button(btn_row2, text="Clone Phrase", command=self._clone_phrase, bootstyle="secondary")
        self._clone_btn.pack(side=tk.LEFT)
        ttk.Button(btn_row3, text="Import", command=self._import_phrases, bootstyle="secondary").pack(side=tk.LEFT, padx=(0, 4))
        self._export_btn = ttk.Button(btn_row3, text="Export", command=self._export_phrases, bootstyle="secondary")
        self._export_btn.pack(side=tk.LEFT)
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        self._tree = ttk.Treeview(tree_frame, show="tree", height=18, selectmode="extended")
        tree_scroll = ttk.Scrollbar(tree_frame)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.config(yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self._tree.yview)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_tree_double)
        self._tree.bind("<Delete>", lambda e: self._delete())
        self._tree.bind("<ButtonPress-1>", self._on_tree_click, add="+")
        self._setup_drag_drop()
        self._tree.tag_configure("dup_abbr", background="#6e2222", foreground="#ffffff")
        self.root.bind("<Escape>", lambda e: self._deselect())

        # Right: phrase preview (manually styled for dark mode)
        right = ttk.Frame(paned, padding="8 0 0 0")
        paned.add(right, weight=1)
        self._right_label = ttk.Label(right, text="Select a folder or phrase, or use Add Phrase.", font=("Segoe UI", 10, "bold"))
        self._right_label.pack(anchor=tk.W)
        self._preview_sep = ttk.Separator(right, orient=tk.HORIZONTAL)
        self._preview_sep.pack(fill=tk.X, pady=(2, 4))
        self._preview_abbr_label = ttk.Label(right, text="")
        self._preview_abbr_label.pack(anchor=tk.W, pady=(0, 2))
        self._preview_editor = RichTextEditor(right, height=20, show_toolbar=False, readonly=True, font_size_offset=self._get_font_offset())
        self._preview_editor.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        # Click anywhere on the right panel to deselect
        for widget in (right, self._right_label, self._preview_sep, self._preview_abbr_label):
            widget.bind("<ButtonPress-1>", lambda e: self._deselect())
        # Apply row height (and any other font-dependent styles) now that the tree exists.
        self._apply_font_settings()
        self._update_selection_dependent_buttons()

    def _get_font_offset(self):
        if not self._get_settings:
            return 0
        return {"small": 0, "medium": 2, "large": 4}.get(
            self._get_settings().get("font_size", "small"), 0
        )

    def _apply_font_settings(self):
        off = self._get_font_offset()
        base = 10 + off
        self._tree.tag_configure("folder", font=("Segoe UI", base, "bold"))
        self._tree.tag_configure("phrase", font=("Segoe UI", base))
        # Row height must be at least the line height of the font plus a little padding.
        import tkinter.font as tkFont
        row_height = tkFont.Font(family="Segoe UI", size=base, weight="bold").metrics("linespace") + 4
        ttk.Style().configure("Treeview", rowheight=row_height)
        if hasattr(self, "_preview_editor"):
            self._preview_editor.apply_font_size(off)
        self._resize_left_panel()

    def _refresh_tree(self):
        # Clear selection first: deleting/rebuilding rows while an iid stays selected
        # can leave the Treeview in a bad state (stale row / "ghost" items on screen).
        try:
            sel = self._tree.selection()
            if sel:
                self._tree.selection_remove(*sel)
        except tk.TclError:
            pass
        self._recompute_duplicate_abbrev_metadata()
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
        self._resize_left_panel()
        self._tree.update_idletasks()
        self._update_duplicate_banner()
        self._update_selection_dependent_buttons()

    def _recompute_duplicate_abbrev_metadata(self):
        root = self._get_data().get("children", [])
        self._dup_ab_phrase_ids = data_model.duplicate_trigger_phrase_ids(root)
        self._dup_ab_folder_ids = data_model.duplicate_trigger_ancestor_folder_ids(root)

    def _update_duplicate_banner(self):
        if not getattr(self, "_dup_banner", None):
            return
        if self._dup_ab_phrase_ids:
            self._dup_banner.config(
                text=(
                    "Multiple phrases with the same abbreviation detected. Please change them "
                    "(highlighted in the list). No two phrases can have the same abbreviation."
                )
            )
            self._dup_banner.pack_forget()
            self._dup_banner.pack(side=tk.LEFT, padx=(10, 8), pady=2, after=self._file_menubutton)
        else:
            self._dup_banner.pack_forget()

    def _resize_left_panel(self):
        """Grow the left tree panel to fit the widest item label."""
        try:
            folder_font = tkFont.Font(family="Segoe UI", size=10, weight="bold")
            phrase_font = tkFont.Font(family="Segoe UI", size=10)
            try:
                indent = int(self._tree.tk.call(str(self._tree), "cget", "-indent"))
            except Exception:
                indent = 20
            max_px = 200
            def measure_items(parent_iid, depth):
                nonlocal max_px
                for iid in self._tree.get_children(parent_iid):
                    data = self._tree.item(iid)
                    text = data.get("text", "")
                    tags = data.get("tags", ())
                    font = folder_font if "folder" in tags else phrase_font
                    px = depth * indent + font.measure(text) + 48
                    if px > max_px:
                        max_px = px
                    measure_items(iid, depth + 1)
            measure_items("", 0)
            screen_w = self.root.winfo_screenwidth()
            new_width = max(280, min(max_px, screen_w // 2))
            self._left_frame.configure(width=new_width)
            self._tree.column("#0", width=new_width - 22, minwidth=150)
        except Exception:
            logging.exception("Failed to auto-resize left panel.")

    def _insert_item(self, parent_iid, item):
        item_id = item.get("id")
        if item.get("type") == "folder":
            name = item.get("name") or "New Folder"
            tags = ["folder"]
            if item_id in getattr(self, "_dup_ab_folder_ids", ()):
                tags.append("dup_abbr")
            iid = self._tree.insert(parent_iid, tk.END, iid=item_id, text="\U0001f4c1 " + name, tags=tuple(tags))
            for child in item.get("children", []):
                self._insert_item(iid, child)
        else:
            name = item.get("name") or "(no name)"
            tags = ["phrase"]
            if item_id in getattr(self, "_dup_ab_phrase_ids", ()):
                tags.append("dup_abbr")
            iid = self._tree.insert(parent_iid, tk.END, iid=item_id, text="\U0001f4c4 " + name, tags=tuple(tags))

    def _setup_drag_drop(self):
        self._drag_iid = None
        self._drop_target_iid = None
        self._drop_mode = None  # "into" | "before" | "after"
        self._tree.tag_configure("drop_target_into", background="#cce0ff")
        # Thin line shown between items when dropping "between" (no row highlight)
        self._drop_line = tk.Toplevel(self._tree)
        self._drop_line.overrideredirect(True)
        self._drop_line.configure(bg="#ffffff")
        self._drop_line.withdraw()
        self._tree.bind("<ButtonPress-1>", self._on_drag_start, add="+")
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
            self._drop_line.withdraw()
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
            self._deselect()

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
                        abs_x = self._tree.winfo_rootx()
                        abs_y = self._tree.winfo_rooty() + line_y - 1
                        w = self._tree.winfo_width()
                        self._drop_line.geometry(f"{w}x2+{abs_x}+{abs_y}")
                        self._drop_line.deiconify()
                        self._drop_line.lift()
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

    def _deselect(self):
        try:
            sel = self._tree.selection()
            if sel:
                self._tree.selection_remove(*sel)
        except tk.TclError:
            pass
        self._update_selection_dependent_buttons()

    def _on_tree_click(self, event):
        """Deselect when clicking on empty space in the tree."""
        if not self._tree.identify_row(event.y):
            self._deselect()

    def _selected_phrases_in_tree_order(self):
        """All currently selected items that are phrases, in top-to-bottom tree order."""
        sel = set(self._tree.selection())
        if not sel:
            return []
        ordered = []

        def walk(children):
            for item in children:
                if item.get("type") == "phrase" and item.get("id") in sel:
                    ordered.append(item)
                elif item.get("type") == "folder":
                    walk(item.get("children", []))

        walk(self._get_data().get("children", []))
        return ordered

    def _selected_export_roots(self):
        """Selected nodes that are not under another selected node (each becomes an export root)."""
        sel = set(self._tree.selection())
        if not sel:
            return []
        roots = []

        def walk(children, path_ids):
            for item in children:
                iid = item.get("id")
                path_here = path_ids + [iid]
                if iid in sel:
                    sel_anc = [x for x in path_ids if x in sel]
                    if not sel_anc:
                        roots.append(item)
                if item.get("type") == "folder":
                    walk(item.get("children", []), path_here)

        walk(self._get_data().get("children", []), [])
        return roots

    def _update_selection_dependent_buttons(self):
        """Enable/disable toolbar buttons based on selection count and types."""
        if not getattr(self, "_export_btn", None):
            return
        sel = self._tree.selection()
        n = len(sel)
        single = n == 1
        if self._rename_btn:
            self._rename_btn.config(state=tk.NORMAL if single else tk.DISABLED)
        one_phrase = False
        if single:
            item = self._get_selected_item_and_parent()[0]
            one_phrase = bool(item and item.get("type") == "phrase")
        if self._edit_btn:
            self._edit_btn.config(state=tk.NORMAL if one_phrase else tk.DISABLED)
        if self._clone_btn:
            self._clone_btn.config(state=tk.NORMAL if one_phrase else tk.DISABLED)
        export_roots = self._selected_export_roots()
        self._export_btn.config(state=tk.NORMAL if export_roots else tk.DISABLED)

    def _export_phrases(self):
        roots = self._selected_export_roots()
        if not roots:
            _show_info_dialog(self.root, "Export", "Nothing selected to export.")
            return
        out_dir = data_model._resolve_data_dir()
        os.makedirs(out_dir, exist_ok=True)
        if len(roots) == 1:
            base = "Exported " + _sanitize_export_filename_part(roots[0].get("name"))
        else:
            base = "Exported Items"
        dest = os.path.join(out_dir, base + ".json")
        n = 1
        while os.path.exists(dest):
            n += 1
            dest = os.path.join(out_dir, "%s (%d).json" % (base, n))
        payload = {
            "export_version": 2,
            "app": "copasta",
            "items": [copy.deepcopy(r) for r in roots],
        }
        try:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except OSError:
            logging.exception("Failed writing phrase export file.")
            _show_info_dialog(self.root, "Export", "Could not write the export file.")
            return
        _open_explorer_select(dest)

    def _import_phrases(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Import",
            initialdir=_downloads_folder(),
            filetypes=[("Copasta export", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            parsed = _parse_import_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            msg = str(e) if str(e) else type(e).__name__
            _show_info_dialog(self.root, "Import", "Could not read this file.\n\n%s" % msg)
            return
        target_list, _ = self._get_import_target_list()
        new_ids = []

        def collect_ids(node):
            ids = [node.get("id")]
            if node.get("type") == "folder":
                for ch in node.get("children", []):
                    ids.extend(collect_ids(ch))
            return [x for x in ids if x]

        if parsed["mode"] == "tree":
            for src in parsed["items"]:
                cloned = _clone_tree_new_ids(src)
                target_list.append(cloned)
                new_ids.extend(collect_ids(cloned))
        else:
            for src in parsed["phrases"]:
                p = copy.deepcopy(src)
                p["id"] = _new_id()
                data_model._ensure_phrase(p)
                target_list.append(p)
                new_ids.append(p["id"])
        self._save_data(self._get_data())
        self._refresh_tree()
        if len(new_ids) == 1:
            self._tree.selection_set(new_ids[0])
            self._tree.see(new_ids[0])
        elif new_ids:
            self._tree.selection_set(*new_ids)

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
        self._update_selection_dependent_buttons()
        phrases = self._selected_phrases_in_tree_order()
        if len(phrases) >= 2:
            self._right_label.config(text="%d phrases selected" % len(phrases))
            self._preview_abbr_label.config(text="")
            self._preview_editor.set_html("")
        elif len(phrases) == 1:
            item = phrases[0]
            html = item.get("expansion_html") or ""
            trig = (item.get("trigger") or "").strip()
            self._right_label.config(text="Phrase Preview")
            self._preview_abbr_label.config(text=("Abbreviation: %s" % trig) if trig else "No abbreviation set")
            self._preview_editor.set_html(html)
        else:
            self._preview_editor.set_html("")
            self._preview_abbr_label.config(text="")
            self._right_label.config(text="Select a folder or phrase, or use Add Phrase.")

    def _on_tree_double(self, event):
        item, _, _ = self._get_selected_item_and_parent()
        if item and item.get("type") == "phrase":
            self._edit_phrase()

    def _get_import_target_list(self):
        """
        List to append new items to (phrases on import, phrases on Add Phrase, folders on
        New Folder). Uses the first selected row in depth-first tree order: a folder means
        add inside that folder; a phrase means add in the same list as that phrase. No
        selection means root.
        """
        data = self._get_data()
        root = data.get("children", [])
        sel = set(self._tree.selection())
        if not sel:
            return root, None

        def first_selected(children):
            for item in children:
                if item.get("id") in sel:
                    return item
                if item.get("type") == "folder":
                    hit = first_selected(item.get("children", []))
                    if hit is not None:
                        return hit
            return None

        hit = first_selected(root)
        if hit is None:
            return root, None
        if hit.get("type") == "folder":
            return hit.setdefault("children", []), hit
        _, lst, _ = self._find_item_by_iid(root, "", hit.get("id"))
        return lst if lst is not None else root, None

    def _get_current_folder_children(self):
        """Return (list to add to, parent folder or None). Same depth-first rule as Import Phrase."""
        return self._get_import_target_list()

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
        self._tree.selection_set(folder["id"])
        self._tree.see(folder["id"])

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
            self._tree.selection_set(item["id"])
            self._tree.see(item["id"])

    def _selected_items_deepest_first(self):
        """Selected folders/phrases as (item, parent_list), deepest in tree first for safe removal."""
        sel = set(self._tree.selection())
        if not sel:
            return []
        acc = []

        def walk(children, depth):
            for item in children:
                if item.get("id") in sel:
                    acc.append((depth, item, children))
                if item.get("type") == "folder":
                    walk(item.get("children", []), depth + 1)

        walk(self._get_data().get("children", []), 0)
        acc.sort(key=lambda t: -t[0])
        return [(item, lst) for _, item, lst in acc]

    def _delete(self):
        pairs = self._selected_items_deepest_first()
        if not pairs:
            _show_info_dialog(self.root, "Delete", "Select a folder or phrase first.")
            return
        n = len(pairs)
        labels = []
        for item, _ in pairs[:15]:
            kind = "folder" if item.get("type") == "folder" else "phrase"
            nm = item.get("name") or ("(no name)" if kind == "phrase" else "folder")
            labels.append("\u2018%s\u2019 (%s)" % (nm, kind))
        more = "" if n <= 15 else "\n... and %d more." % (n - 15)
        body = "Delete %d item(s)?\n\n%s%s" % (n, "\n".join(labels), more)
        if not _ask_yesno_dialog(self.root, "Delete", body):
            return
        for item, lst in pairs:
            for i, x in enumerate(lst):
                if x is item:
                    lst.pop(i)
                    break
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
            font_size_offset=self._get_font_offset(),
        )
        self._wait_dialog(d)
        if getattr(d, "_result", False) and d._phrase:
            self._tree.selection_set(d._phrase["id"])
            self._tree.see(d._phrase["id"])

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
            font_size_offset=self._get_font_offset(),
        )
        self._wait_dialog(d)
        if getattr(d, "_result", False):
            self._tree.selection_set(item["id"])
            self._tree.see(item["id"])

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
            "trigger_type": "Auto",
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
            font_size_offset=self._get_font_offset(),
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

    def _wait_dialog(self, d):
        self.root.wait_window(d)

    def _open_settings(self):
        if self._on_settings:
            self._on_settings()

    def _show_about(self):
        version = self._app_version or "unknown"
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "About Copasta",
                f"Copasta {version}\n\n"
                "A clipboard / phrase-paste utility.\n\n"
                "Updates are delivered automatically from GitHub.",
                parent=self.root,
            )
        except Exception:
            logging.exception("Failed to show About dialog")

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

    def _quit(self):
        self._save_geometry()
        if self._on_quit:
            self._on_quit()
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

        ttk.Label(self, text="Popup position").pack(anchor=tk.W, padx=8, pady=(12, 4))
        self._pos_var = tk.StringVar(value=s.get("floating_menu_position", "cursor"))
        ttk.Radiobutton(self, text="At text cursor location", variable=self._pos_var, value="cursor").pack(anchor=tk.W, padx=8)
        ttk.Radiobutton(self, text="At mouse cursor location", variable=self._pos_var, value="mouse").pack(anchor=tk.W, padx=8)
        ttk.Radiobutton(self, text="Fixed custom position", variable=self._pos_var, value="fixed").pack(anchor=tk.W, padx=8)
        ttk.Button(self, text="Drag window to set position...", command=self._open_position_picker).pack(anchor=tk.W, padx=8, pady=4)

        ttk.Label(self, text="Font size").pack(anchor=tk.W, padx=8, pady=(12, 4))
        self._font_size_var = tk.StringVar(value=s.get("font_size", "small"))
        ttk.Radiobutton(self, text="Small", variable=self._font_size_var, value="small").pack(anchor=tk.W, padx=8)
        ttk.Radiobutton(self, text="Medium", variable=self._font_size_var, value="medium").pack(anchor=tk.W, padx=8)
        ttk.Radiobutton(self, text="Large", variable=self._font_size_var, value="large").pack(anchor=tk.W, padx=8)

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

    def _start_recording(self, target_var, on_apply):
        """Start listening for the next key combo and call on_apply(combo, remover) when captured."""
        import keyboard
        if getattr(self, "_hotkey_hook", None):
            try:
                self._hotkey_hook()
            except Exception:
                logging.exception("Failed removing existing settings hotkey hook.")
            self._hotkey_hook = None
        target_var.set("(press key combo...)")
        self._recording = [True]
        self._active_modifiers = set()

        def norm(name):
            n = (name or "").strip().lower()
            aliases = {
                "left ctrl": "ctrl", "right ctrl": "ctrl", "control": "ctrl",
                "left shift": "shift", "right shift": "shift", "skift": "shift",
                "vänster skift": "shift", "hoger skift": "shift", "höger skift": "shift",
                "left alt": "alt", "right alt": "alt", "alt gr": "alt", "altgr": "alt",
                "left windows": "win", "right windows": "win", "windows": "win",
            }
            return aliases.get(n, n)

        def is_modifier_like(name, scan_code=None):
            n = (name or "").strip().lower()
            if scan_code in (42, 54, 29, 3613, 56, 3640, 3675, 3676):
                return True
            if n in ("ctrl", "shift", "alt", "win"):
                return True
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
                if ("ctrl" in self._active_modifiers or safe_pressed("ctrl")
                        or safe_pressed("left ctrl") or safe_pressed("right ctrl")
                        or safe_pressed("control")):
                    parts.append("ctrl")
                if ("shift" in self._active_modifiers or safe_pressed("shift")
                        or safe_pressed("left shift") or safe_pressed("right shift")):
                    parts.append("shift")
                if ("alt" in self._active_modifiers or safe_pressed("alt")
                        or safe_pressed("left alt") or safe_pressed("right alt")
                        or safe_pressed("alt gr") or safe_pressed("altgr")):
                    parts.append("alt")
                if ("win" in self._active_modifiers or safe_pressed("windows")
                        or safe_pressed("left windows") or safe_pressed("right windows")
                        or safe_pressed("win")):
                    parts.append("win")
                parts.append(key_name)
                combo = "+".join(dict.fromkeys(p for p in parts if p))
                remover = getattr(self, "_hotkey_hook", None)
                self._recording[0] = False
                self.after(0, lambda: on_apply(combo, remover))
            except Exception:
                logging.exception("Settings hotkey record handler failed.")

        self._hotkey_hook = keyboard.on_press(on_key)

    def _record_hotkey(self):
        self._pending_hotkey = None
        try:
            self._save_hotkey_btn.pack_forget()
        except Exception:
            logging.exception("Failed to hide hotkey save button before recording.")
        self._start_recording(self._hotkey_var, self._apply_recorded_hotkey)

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
        s["floating_menu_position"] = self._pos_var.get()
        s["font_size"] = self._font_size_var.get()
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
