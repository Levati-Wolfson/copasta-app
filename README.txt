Copasta

A Windows desktop app for storing and pasting rich text phrases. Supports folders, auto-expand abbreviations, and a global floating phrase menu.

GitHub: https://github.com/Levati-Wolfson/copasta-app

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
First-time installation (Windows)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Open the latest release on GitHub:
       https://github.com/Levati-Wolfson/copasta-app/releases

  2. Download Copasta.zip (the main download for that release).

  3. Unzip it (right-click the zip → Extract All, or open it and drag the
     folder out). You should get a folder named Copasta containing:
       • Copasta.exe   — the program you run
       • _internal\    — support files (leave this folder next to Copasta.exe)

  4. Double-click Copasta.exe inside that Copasta folder.

  5. Put the whole Copasta folder somewhere you will keep it, for example:
       Documents\Copasta
       or a folder on your Desktop.
     Avoid installing under Program Files unless you need to; updates there
     may ask for an extra Windows permission click.

  6. Optional: right-click Copasta.exe → Pin to taskbar, or Send to →
     Desktop (create shortcut). The shortcut must still point at Copasta.exe
     inside the Copasta folder (with _internal beside it).

  Do not copy only Copasta.exe to another location without the _internal
  folder — the app will not run correctly.

  The small Copasta.zip.sha256 file on the release page is used automatically
  when Copasta updates itself; you do not need to download it for a first install.

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
  All data (folders, phrases, settings) is stored in a single file, Phrases.json,
  kept in the same folder as Copasta.exe. Nothing is written to AppData or anywhere
  else on the system.
  This means you can:
    • Move or copy the entire folder to another device and take all your phrases
      with you.
    • Store the folder in Dropbox or OneDrive to sync phrases across devices
      automatically.
  Note: if you move the folder after enabling "Start with Windows", untick and
  re-tick that option so the startup shortcut points to the new location.

System tray
  Closing the main window minimises Copasta to the system tray.
  Right-click the tray icon to Show, Check for updates, or Quit the app.

Automatic updates
  Copasta checks GitHub for a new version every time it starts. When a new
  version is available you'll see a small dialog with release notes and three
  choices:
    • Install now — downloads Copasta.zip, checks it, replaces the files in
      your Copasta folder, and restarts (usually under a minute).
    • Later — no action; you'll be asked again next time you launch Copasta.
    • Skip this version — no prompt for this version; the next version after
      it will still prompt.
  You can also check manually at any time via Help → Check for updates...,
  or from the system tray menu.
  If Copasta is installed in a protected folder like Program Files, Windows
  will show a single User Account Control prompt during the update — click
  Yes to allow it to replace itself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Troubleshooting
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If auto-expand or the global hotkey do not work, try running Copasta as
Administrator (right-click Copasta.exe → "Run as administrator"). Some
applications block global keyboard hooks from non-elevated processes.
