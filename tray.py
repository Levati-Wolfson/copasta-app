"""System tray icon and menu."""
import threading

from PIL import Image, ImageDraw
import pystray

import app_icon


def _fallback_tray_image(size=64):
    """Minimal placeholder if Newicon.png is missing."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, size - 4, size - 4], fill=(70, 130, 180), outline=(255, 255, 255), width=2)
    draw.rectangle([12, 20, 28, 44], fill="white")
    draw.rectangle([36, 20, 52, 44], fill="white")
    return img


def run_tray(show_callback, quit_callback, check_for_updates_callback=None):
    """
    Run system tray icon in a separate thread.
    show_callback: call when user clicks "Show"
    quit_callback: call when user clicks "Quit"
    check_for_updates_callback: optional; if provided, adds "Check for updates..." item
    """
    icon_image = app_icon.load_tray_image(64) or _fallback_tray_image(64)

    def on_show(icon, item):
        show_callback()

    def on_quit(icon, item):
        quit_callback()
        icon.stop()

    def on_check_for_updates(icon, item):
        if check_for_updates_callback is not None:
            check_for_updates_callback()

    menu_items = [pystray.MenuItem("Show", on_show, default=True)]
    if check_for_updates_callback is not None:
        menu_items.append(pystray.MenuItem("Check for updates...", on_check_for_updates))
    menu_items.append(pystray.MenuItem("Quit", on_quit))
    menu = pystray.Menu(*menu_items)
    icon = pystray.Icon("Copasta", icon_image, "Copasta", menu)

    def run():
        icon.run()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return icon
