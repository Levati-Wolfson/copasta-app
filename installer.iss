[Setup]
AppId={{8A0E7F63-DF57-4C66-8F84-96E127A34042}
AppName=Copasta
; Version is defined in main.py APP_VERSION -- keep these in sync when releasing.
AppVersion=1.0.0
AppPublisher=Copasta
DefaultDirName={autopf}\Copasta
DefaultGroupName=Copasta
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=CopastaSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\Copasta.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Copasta"; Filename: "{app}\Copasta.exe"
Name: "{autodesktop}\Copasta"; Filename: "{app}\Copasta.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\Copasta.exe"; Description: "Launch Copasta"; Flags: nowait postinstall skipifsilent
