"""
Copasta - Windows desktop app.
Folders, rich text paste, Auto/Hotkey triggers, floating phrase menu.
"""
import sys
import os
import logging

APP_VERSION = "1.0.0"

import data_model
import expansion
import gui
import tray
import clipboard_paste
import floating_menu


def _setup_logging():
    from logging.handlers import RotatingFileHandler

    data_dir = data_model._resolve_data_dir()
    log_path = os.path.join(data_dir, "copasta.log")
    handler = RotatingFileHandler(
        log_path, maxBytes=512_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.info("Logging initialized: %s", log_path)


def main():
    _setup_logging()
    data = data_model.load_data()

    def get_data():
        return data

    def get_children():
        return data.get("children", [])

    def get_settings():
        return data.get("settings", data_model.DEFAULT_SETTINGS.copy())

    def save_data(new_data=None):
        if new_data is not None and new_data is not data:
            data["children"] = new_data.get("children", [])
            data["settings"] = new_data.get("settings", data.get("settings", {}))
        data_model.save_data(data)

    # Expansion engine (Auto + Hotkey, clipboard paste)
    engine = expansion.ExpansionEngine(get_children, get_settings)
    engine.start()

    def paste_phrase(phrase_item):
        clipboard_paste.paste_rich_text(phrase_item.get("expansion_html") or "")

    def save_floating_position(x, y):
        s = get_settings()
        s["floating_menu_x"] = x
        s["floating_menu_y"] = y
        s["floating_menu_position"] = "fixed"
        data_model.save_data(data)

    floating = floating_menu.FloatingMenu(get_data, get_settings, paste_phrase, on_save_position=save_floating_position)
    floating_hotkey_remove = [None]

    def register_floating_hotkey():
        if floating_hotkey_remove[0]:
            try:
                floating_hotkey_remove[0]()
            except Exception:
                pass
        import keyboard
        hotkey = get_settings().get("floating_menu_hotkey", "ctrl+shift+space")
        try:
            floating_hotkey_remove[0] = keyboard.add_hotkey(hotkey, lambda: floating.show(), suppress=True)
        except Exception:
            floating_hotkey_remove[0] = None

    register_floating_hotkey()

    # Main window
    dashboard = gui.MainWindow(
        get_data,
        save_data,
        get_settings=get_settings,
        save_settings=lambda s: data_model.save_data(data),
        on_close_callback=lambda: dashboard.hide(),
        on_settings_callback=None,
    )
    # Apply saved theme (dark mode) only after window is ready
    dashboard.root.after(100, lambda: gui.apply_theme(dashboard.root, get_settings))

    def open_settings():
        # Disable floating window hotkey while settings are open
        if floating_hotkey_remove[0]:
            try:
                floating_hotkey_remove[0]()
            except Exception:
                pass
            floating_hotkey_remove[0] = None

        def save_xy(x, y):
            s = get_settings()
            s["floating_menu_x"] = x
            s["floating_menu_y"] = y
            s["floating_menu_position"] = "fixed"
            data_model.save_data(data)

        def persist_settings(s):
            data_model.save_data(data)

        d = gui.SettingsDialog(
            dashboard.root,
            get_settings,
            persist_settings,
            on_position_picker=lambda dlg: _open_position_picker(dlg, save_xy),
        )
        def on_settings_ok():
            gui.apply_theme(dashboard.root, get_settings)
            engine.refresh_hotkeys()
        d.set_on_ok(on_settings_ok)
        d.grab_set()
        try:
            dashboard.root.wait_window(d)
        finally:
            register_floating_hotkey()

    def _open_position_picker(settings_dialog, save_xy):
        # Enforce a single picker window at a time.
        existing = getattr(settings_dialog, "_position_picker_win", None)
        if existing:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass

        settings_dialog.grab_release()
        def restore_settings_grab():
            try:
                if settings_dialog.winfo_exists():
                    settings_dialog.grab_set()
            except Exception:
                pass

        picker_win = floating_menu.run_position_picker(
            dashboard.root,
            save_xy,
            on_close=restore_settings_grab,
        )

        settings_dialog._position_picker_win = picker_win

        if not getattr(settings_dialog, "_picker_destroy_bound", False):
            def close_picker_on_settings_destroy(_event=None):
                p = getattr(settings_dialog, "_position_picker_win", None)
                if not p:
                    return
                try:
                    if p.winfo_exists():
                        p.destroy()
                except Exception:
                    pass
                settings_dialog._position_picker_win = None

            settings_dialog.bind("<Destroy>", close_picker_on_settings_destroy, add="+")
            settings_dialog._picker_destroy_bound = True

    # Re-attach settings: MainWindow was built without on_settings_callback; we need to open settings
    dashboard._on_settings = open_settings

    def on_phrase_save():
        engine.refresh_hotkeys()

    dashboard.set_phrase_save_callback(on_phrase_save)

    tray_icon = None

    def show_window():
        dashboard.show()

    def quit_app():
        def do_quit():
            engine.stop()
            if floating_hotkey_remove[0]:
                try:
                    floating_hotkey_remove[0]()
                except Exception:
                    pass
            floating.destroy()
            if tray_icon:
                try:
                    tray_icon.stop()
                except Exception:
                    pass
            dashboard.destroy()
            sys.exit(0)

        dashboard.root.after(0, do_quit)

    dashboard._on_close = lambda: dashboard.hide()
    tray_icon = tray.run_tray(show_window, quit_app)

    dashboard.run()


if __name__ == "__main__":
    main()
