"""System tray icon and menu."""
import threading

from PIL import Image, ImageDraw
import pystray


def create_icon_image(size=64):
    """Create a simple icon for the system tray."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded rectangle (steel blue)
    draw.rounded_rectangle([4, 4, size - 4, size - 4], fill=(70, 130, 180), outline=(255, 255, 255), width=2)
    # Simple "ab" style: two blocks suggesting text
    draw.rectangle([12, 20, 28, 44], fill="white")
    draw.rectangle([36, 20, 52, 44], fill="white")
    return img


def run_tray(show_callback, quit_callback):
    """
    Run system tray icon in a separate thread.
    show_callback: call when user clicks "Show"
    quit_callback: call when user clicks "Quit"
    """
    icon_image = create_icon_image(64)

    def on_show(icon, item):
        show_callback()

    def on_quit(icon, item):
        quit_callback()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Show", on_show, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("Copasta", icon_image, "Copasta", menu)

    def run():
        icon.run()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return icon
