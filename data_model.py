"""Data model: folders, phrases, settings. Load/save from JSON."""
import json
import os
import sys
import uuid


def _resolve_data_dir():
    """
    Resolve where Phrases.json is stored.

    - Bundled .exe: always next to the .exe (portable-only distribution).
    - Dev (source): next to the .py files.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_DATA_DIR = _resolve_data_dir()
DATA_FILE = os.path.join(_DATA_DIR, "Phrases.json")

# Migrate from old filename if needed (silent, one-time)
_OLD_DATA_FILE = os.path.join(_DATA_DIR, "phrases.json")
if not os.path.exists(DATA_FILE) and os.path.exists(_OLD_DATA_FILE):
    try:
        os.rename(_OLD_DATA_FILE, DATA_FILE)
    except OSError:
        pass

DEFAULT_SETTINGS = {
    "floating_menu_hotkey": "ctrl+shift+space",
    "floating_menu_position": "cursor",  # "cursor", "mouse", or "fixed"
    "floating_menu_x": 100,
    "floating_menu_y": 100,
    "start_with_windows": False,
    "window_geometry": "750x500",
}


def _new_id():
    return str(uuid.uuid4())


def _ensure_folder(item):
    if item.get("type") != "folder":
        item["type"] = "folder"
    if "id" not in item:
        item["id"] = _new_id()
    if "name" not in item:
        item["name"] = "New Folder"
    if "children" not in item:
        item["children"] = []
    return item


def _ensure_phrase(item):
    if item.get("type") != "phrase":
        item["type"] = "phrase"
    if "id" not in item:
        item["id"] = _new_id()
    if "name" not in item:
        item["name"] = ""
    if "trigger" not in item:
        item["trigger"] = ""
    if "expansion_html" not in item:
        item["expansion_html"] = ""
    return item


def _normalize_tree(children):
    """Normalize a list of folder/phrase items."""
    out = []
    for item in children:
        if item.get("type") == "folder":
            _ensure_folder(item)
            item["children"] = _normalize_tree(item.get("children", []))
            out.append(item)
        else:
            _ensure_phrase(item)
            out.append(item)
    return out


def load_data():
    """Load phrases.json. Returns { "children": [...], "settings": {...} }."""
    if not os.path.exists(DATA_FILE):
        return {"children": [], "settings": DEFAULT_SETTINGS.copy()}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        data = {"children": [], "settings": DEFAULT_SETTINGS.copy()}
    # Migrate old flat format: { "trigger": "expansion", ... }
    if "children" not in data and isinstance(data, dict) and not any(k in data for k in ("children", "settings")):
        legacy_phrases = data
        data = {"children": [], "settings": DEFAULT_SETTINGS.copy()}
        for trigger, expansion in legacy_phrases.items():
            if isinstance(expansion, str):
                data["children"].append({
                    "type": "phrase",
                    "id": _new_id(),
                    "name": trigger,
                    "trigger": trigger,
                    "expansion_html": "<p>%s</p>" % expansion.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                })
    if "children" not in data:
        data["children"] = []
    data["children"] = _normalize_tree(data["children"])
    if "settings" not in data:
        data["settings"] = DEFAULT_SETTINGS.copy()
    for k, v in DEFAULT_SETTINGS.items():
        if k not in data["settings"]:
            data["settings"][k] = v
    return data


def save_data(data):
    """Save to phrases.json atomically (write temp file, then rename)."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DATA_FILE)


def collect_all_phrases(children):
    """Flatten: list of all phrase dicts."""
    out = []
    for item in children:
        if item.get("type") == "phrase":
            out.append(item)
        elif item.get("type") == "folder":
            out.extend(collect_all_phrases(item.get("children", [])))
    return out


def collect_auto_triggers(children):
    """Return dict trigger -> phrase item for all phrases that have an abbreviation set."""
    result = {}
    for p in collect_all_phrases(children):
        t = (p.get("trigger") or "").strip()
        if t:
            result[t] = p
    return result
