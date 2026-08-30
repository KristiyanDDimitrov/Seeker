; Inno Setup script for seeker-ui (the desktop app) — the Windows
; equivalent of packaging/dmg_settings.py: takes the same PyInstaller
; onedir build (packaging/seeker.spec's COLLECT() output, dist/Seeker/)
; and wraps it into a real installer with Start Menu/Desktop shortcuts
; and a standard uninstall entry — the closest Windows equivalent to
; the .dmg's drag-to-install experience.
;
; Requires Inno Setup (https://jrsoftware.org/isinfo.php) installed
; separately on the build machine — unlike dmgbuild, there's no Python
; package that compiles .iss files; ISCC.exe (its command-line compiler)
; needs to be installed once, the same way a real Docker install is a
; separate prerequisite for slskd. See packaging/build_windows_installer.py
; for the one-command chained build (PyInstaller, then ISCC).
;
; WRITTEN BUT NOT VERIFIED ON A REAL WINDOWS MACHINE — no such
; environment exists in this project's development session (see
; CLAUDE.md roadmap item 36 and README's packaging section). Treat this
; the same way seeker.spec's own Windows/Linux rows were already
; documented: cross-platform by construction, not proven by a real run.
;
; AppId is a fixed, randomly-generated GUID — Inno Setup uses this to
; recognize "this is the same app" across versions/reinstalls (so a
; future upgrade replaces in place rather than installing side by
; side). Generated once for this project; never change it.

#define MyAppName "Seeker"
#define MyAppVersion "0.1.0"
#define MyAppExeName "Seeker.exe"
#define MyDistDir "..\dist\Seeker"

[Setup]
AppId={{08479AF0-7643-4688-B183-4E3A3431DE4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Installer/uninstaller executable icon — packaging/icons/seeker_icon.ico,
; a compile-time-only path (Inno Setup embeds it directly into
; Setup.exe), not something that needs to exist on the target machine.
SetupIconFile=icons\seeker_icon.ico
OutputDir=..\dist
OutputBaseFilename=SeekerSetup
Compression=lzma2
SolidCompression=yes
; PySide6/Qt and this project's other compiled deps (numpy, scipy,
; rapidfuzz) ship 64-bit Windows wheels only — no 32-bit target is
; meaningful here.
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The entire onedir build tree (Seeker.exe plus every bundled
; dependency, including docker-compose.yml — see seeker.spec's own
; datas entry) — mirrors the .dmg copying the whole .app bundle.
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Installed alongside Seeker.exe so the [Icons] entries below have a
; real on-disk path to point IconFilename at (a shortcut's icon path
; must resolve on the target machine, unlike SetupIconFile= above).
Source: "icons\seeker_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\seeker_icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\seeker_icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\seeker_icon.ico"

[Run]
; Matches the .dmg's own "no forced launch" spirit — offered, not
; automatic, and skippable in a silent/unattended install.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
