Copasta

A Windows desktop app for saving commonly used words, phrases or long messages, for easy pasting. Supports folders for phrase storage, abbreviations for automatic pasting, rich text paste, and a global floating phrase menu.

GitHub repository name: copasta-app

Features

- Folders: Hierarchical folder structure in the left sidebar.
- Phrases: Each phrase has a name, trigger type (Auto or Hotkey), and rich text content.
- Auto triggers: Type an abbreviation and it is replaced by the phrase (rich text pasted via clipboard).
- Hotkey triggers: Assign a key combo (e.g. Ctrl+Shift+E) to expand a phrase.
- Rich text: Bold, italic, underline, subscript/superscript, hyperlinks, bulleted/numbered lists are supported. Content is pasted as HTML into the active window (clipboard + Ctrl+V), then your clipboard is restored.
- Global floating menu: Configurable hotkey (default Ctrl+Shift+Space) opens a borderless popup with your phrase library. Mouse over a folder for a cascading side menu; click a phrase to paste it. Hover over a phrase for >0.5s to see a preview tooltip. Pin button (top right) keeps the menu on top as a persistent overlay.
- Settings (File -> Settings): Set the floating menu hotkey and popup position ("At text cursor location", "At mouse cursor location" or "Fixed custom position"). For fixed position, use "Drag window to set position..." to open a semi-transparent window you can drag; click "Save position" to store location. Here you can also choose for the program to start when windows starts.
- Persistence: Data in phrases.json (folders, phrases, settings). Config in config.json (e.g. last trigger type).
- Portable use: In the portable (zip) version, phrases.json and all settings are stored in the same folder as Copasta.exe. This means you can move or copy the entire folder to another device and all your phrases come with it. If you store the folder in Dropbox or OneDrive, your phrases will sync automatically across all your devices. Note: if you move the folder after enabling "Start with Windows", untick and re-tick that setting so the shortcut points to the new location.
- System tray: Close the main window to minimize to the tray; Show / Quit from the tray icon


If expansions or the global hotkey do not work, try running as Administrator.
