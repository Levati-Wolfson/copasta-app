"""Single app icon (Newicon.png) for tray, window title bars, and PyInstaller exe."""
import logging
import os
import sys

from PIL import Image, ImageTk

ICON_FILENAME = "Newicon.png"


def icon_png_path():
    """Resolved path to the PNG (project dir when running from source, bundle when frozen)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ICON_FILENAME)


def load_tray_image(size=64):
    """RGBA PIL Image for pystray, or None if the file is missing."""
    path = icon_png_path()
    if not os.path.isfile(path):
        logging.warning("App icon not found at %s", path)
        return None
    try:
        img = Image.open(path).convert("RGBA")
        if img.size != (size, size):
            img = img.resize((size, size), Image.Resampling.LANCZOS)
        return img
    except Exception:
        logging.exception("Failed to load app icon for tray.")
        return None


def apply_window_icon(root):
    """
    Set title-bar / taskbar icon for this Tk hierarchy (and default for new Toplevels).
    Keeps a reference on root so the image is not garbage-collected.
    """
    path = icon_png_path()
    if not os.path.isfile(path):
        logging.warning("App icon not found at %s", path)
        return
    try:
        pil_img = Image.open(path)
        photo = ImageTk.PhotoImage(pil_img, master=root)
        root.iconphoto(True, photo)
        root._copasta_icon_photo = photo
    except Exception:
        logging.exception("Failed to set window icon.")
