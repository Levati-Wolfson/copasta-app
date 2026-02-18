Copasta

A Windows desktop app that expands abbreviations into rich text. Supports folders, Auto/Hotkey triggers, rich text paste, and a global floating phrase menu.

Features

- Folders: Hierarchical folder structure in the left sidebar (Treeview). New Folder, Rename, Delete.
- Phrases: Each phrase has a name, trigger type (Auto or Hotkey), and rich text content.
- Auto triggers: Type an abbreviation and it is replaced by the phrase (rich text pasted via clipboard).
- Hotkey triggers: Assign a key combo (e.g. Ctrl+Shift+E) to expand a phrase.
- Rich text: Bold, italic, underline, subscript/superscript, hyperlinks, bulleted/numbered lists. Content is pasted as HTML into the active window (clipboard + Ctrl+V), then your clipboard is restored.
- Add/Edit phrase dialog: Single window with name, trigger type, hotkey record button, and rich text editor with toolbar. Last trigger type (Auto/Hotkey) is saved to config.json.
- Global floating menu: Configurable hotkey (default Ctrl+Shift+Space) opens a borderless popup with your phrase library. Click a folder for a cascading side menu; click a phrase to paste it. Hover over a phrase for >0.5s to see a preview tooltip. Pin button (top right) keeps the menu on top as a persistent overlay.
- Settings (File -> Settings): Set the floating menu hotkey and popup position ("At text cursor location" or "Fixed custom position"). For fixed position, use "Drag window to set position..." to open a semi-transparent window you can drag; click "Save position" to store X/Y.
- Persistence: Data in phrases.json (folders, phrases, settings). Config in config.json (e.g. last trigger type).
- System tray: Close the main window to minimize to the tray; Show / Quit from the tray icon.

Requirements

- Python 3.7+
- Windows (keyboard hook, clipboard, tray)

Install dependencies

pip install -r requirements.txt

Or:

pip install keyboard pynput pystray Pillow pywin32

Run the app

python main.py

If expansions or the global hotkey do not work, try running as Administrator.

Usage

1. Run python main.py.
2. Use New Folder / Rename / Delete to manage the tree. Add Phrase / Edit Phrase (or double-click a phrase) to add or edit.
3. In the phrase dialog: set name, choose Auto (type abbreviation) or Hotkey (click Record and press your combo), and edit rich text. Save.
4. Auto: type the abbreviation anywhere to expand. Hotkey: press the combo to paste the phrase.
5. Press the floating menu hotkey (e.g. Ctrl+Shift+Space) to open the phrase menu; click folders for submenus, click a phrase to paste. Use the pin to keep the menu on top.
6. File -> Settings to change the floating hotkey and popup position.
7. Close the main window to minimize to the tray.
