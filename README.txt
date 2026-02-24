Copasta

A Windows desktop app for storing and pasting rich text phrases. Supports folders, auto-expand abbreviations, and a global floating phrase menu.

GitHub: https://github.com/Levati-Wolfson/copasta-app

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Folders
  Organise your phrases in a hierarchical folder structure in the left sidebar.
  Drag and drop to rearrange folders and phrases.

Phrases
  Each phrase has a name, optional abbreviation, and rich text content.
  Add, edit, clone, or delete phrases using the buttons in the main window.
  Double-click a phrase in the list to open it for editing.

Auto-expand
  Give a phrase an abbreviation (e.g. "brg") and type it anywhere — Copasta
  detects the typed text and instantly replaces it with the full rich phrase
  (backspaces out the abbreviation, then pastes the content via clipboard).
  Leave the abbreviation empty if you only want to paste via the floating menu.

Rich text editor
  The phrase editor supports:
    • Bold, italic, underline
    • Subscript and superscript
    • Hyperlinks (hover to preview URL; click in the phrase preview to open)
    • Bulleted and numbered list prefixes
    • Undo / Redo
  Content is pasted as HTML into the active window (clipboard + Ctrl+V), after
  which your original clipboard content is automatically restored.

Global floating menu
  A configurable hotkey (default: Ctrl+Shift+Space) opens a borderless popup
  with your full phrase library.
    • Mouse over a folder to see a cascading side menu.
    • Click any phrase to paste it immediately.
    • Hover over a phrase for half a second to see a rich-text preview tooltip.
    • The pin button (top right) keeps the menu open as a persistent overlay.

Settings  (File → Settings)
  • Phrase window hotkey — the key combo that opens the floating menu.
    Click "Record" to capture a new combo by pressing it.
  • Popup position — "At text cursor location", "At mouse cursor location",
    or "Fixed custom position". For a fixed position, use
    "Drag window to set position..." to drag a semi-transparent overlay to
    the spot you want, then click "Save position".
  • Start when Windows starts — adds Copasta to the Windows startup items.

Phrase preview
  Select any phrase in the main window to see a live preview on the right,
  including the abbreviation (if any) and the formatted content.

Persistence
  All data (folders, phrases, settings) is stored in a single file: Phrases.json.

Portable use
  In the portable (zip) distribution, Phrases.json is stored in the same
  folder as Copasta.exe. This means you can:
    • Move the entire folder to another device and take all your phrases with you.
    • Store the folder in Dropbox or OneDrive to sync phrases across devices
      automatically.
  Note: if you move the folder after enabling "Start with Windows", untick and
  re-tick that option so the startup shortcut points to the new location.

System tray
  Closing the main window minimises Copasta to the system tray.
  Right-click the tray icon to Show the window or Quit the app.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Troubleshooting
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If auto-expand or the global hotkey do not work, try running Copasta as
Administrator (right-click Copasta.exe → "Run as administrator"). Some
applications block global keyboard hooks from non-elevated processes.
