; Inno Setup script → JARVIS-Setup.exe   (iscc /DMyAppVersion=2.0.X installer.iss)
#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif

[Setup]
AppId={{6B0E3B52-7F2C-4C1E-9C3A-4A5E2F0B7D21}
AppName=JARVIS
AppVersion={#MyAppVersion}
AppVerName=JARVIS {#MyAppVersion}
AppPublisher=adamekk778
DefaultDirName={localappdata}\Programs\JARVIS
DefaultGroupName=JARVIS
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=JARVIS-Setup
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\JARVIS.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Ikona na ploše"; GroupDescription: "Zástupci:"
Name: "omniroute"; Description: "OmniRoute: brána k AI modelům zdarma (nainstaluje i Node.js)"; GroupDescription: "AI mozek (doporučeno aspoň jedno):"
Name: "ollama"; Description: "Ollama: offline AI na tvém PC (stáhne ~2 GB model)"; GroupDescription: "AI mozek (doporučeno aspoň jedno):"; Flags: unchecked
Name: "tailscale"; Description: "Tailscale: ovládání z telefonu i mimo domov (zdarma)"; GroupDescription: "Telefon:"; Flags: unchecked

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\JARVIS"; Filename: "{app}\JARVIS.exe"
Name: "{autodesktop}\JARVIS"; Filename: "{app}\JARVIS.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "JARVIS"; ValueType: none; Flags: uninsdeletevalue

[Run]
Filename: "winget"; Parameters: "install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements"; StatusMsg: "Instaluji Node.js (pro OmniRoute)…"; Flags: runhidden waituntilterminated; Tasks: omniroute; Check: not WizardSilent
Filename: "{cmd}"; Parameters: "/c ""set PATH=%PATH%;{commonpf64}\nodejs;{commonpf}\nodejs && npm install -g omniroute"""; StatusMsg: "Instaluji OmniRoute…"; Flags: runhidden waituntilterminated; Tasks: omniroute; Check: not WizardSilent
Filename: "winget"; Parameters: "install -e --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements"; StatusMsg: "Instaluji Ollama…"; Flags: runhidden waituntilterminated; Tasks: ollama; Check: not WizardSilent
Filename: "winget"; Parameters: "install -e --id tailscale.tailscale --silent --accept-package-agreements --accept-source-agreements"; StatusMsg: "Instaluji Tailscale…"; Flags: runhidden waituntilterminated; Tasks: tailscale; Check: not WizardSilent
Filename: "{app}\JARVIS.exe"; Description: "Spustit JARVIS"; Flags: nowait postinstall skipifsilent
Filename: "{app}\JARVIS.exe"; Parameters: "--background"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im JARVIS.exe /f"; Flags: runhidden; RunOnceId: "StopJarvis"
