; Inno Setup script → JARVIS-Setup.exe   (iscc /DMyAppVersion=2.0.X installer.iss)
#ifndef MyAppVersion
  #define MyAppVersion "3.4.0"
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
; only one JARVIS installer at a time: a second one fails on files the first still holds ("CreateFile … kód 5")
SetupMutex=JarvisSetupMutex,Global\JarvisSetupMutex
; the uninstall data in its own folder: an old unins000.dat in {app} that Windows will not let us rewrite (locked,
; hidden/system, foreign permissions) no longer stops the installation at "Ukládají se informace pro odinstalaci"
UninstallFilesDir={app}\uninstall
; a log in %TEMP% ("Setup Log …txt") so a failed installation can be explained
SetupLogging=yes
RestartApplications=no

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Ikona na ploše"; GroupDescription: "Zástupci:"
Name: "omniroute"; Description: "OmniRoute: brána k AI modelům zdarma (nainstaluje i Node.js)"; GroupDescription: "AI mozek (doporučeno aspoň jedno):"
Name: "ollama"; Description: "Ollama: offline AI na tvém PC (stáhne ~2 GB model)"; GroupDescription: "AI mozek (doporučeno aspoň jedno):"; Flags: unchecked
Name: "tailscale"; Description: "Tailscale: ovládání z telefonu i mimo domov (zdarma)"; GroupDescription: "Telefon:"; Flags: unchecked

[InstallDelete]
; the program folder of the previous version: never mix old and new libraries
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
Type: files; Name: "{autoprograms}\JARVIS.lnk"
Type: files; Name: "{autodesktop}\JARVIS.lnk"

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

[Code]
// JARVIS must be fully closed before its files are replaced: Windows refuses to rename a running JARVIS.exe
// ("MoveFile selhala; kód 5. Přístup byl odepřen"). Close it (tray, notch, windows) and wait until the file is free.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode, i: Integer;
  Exe: String;
begin
  Result := '';
  Exe := ExpandConstant('{app}\JARVIS.exe');
  Exec(ExpandConstant('{cmd}'), '/c taskkill /im JARVIS.exe /t /f', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/c taskkill /im unins000.exe /f', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Windows refuses to rewrite a file that is read-only, hidden or system ("CreateFile selhala; kód 5"):
  // clear those on the uninstall data, then drop the old copies next to JARVIS.exe (they now live in {app}\uninstall)
  Exec(ExpandConstant('{cmd}'), '/c attrib -r -h -s "' + ExpandConstant('{app}') + '\unins*.*"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/c attrib -r -h -s "' + ExpandConstant('{app}') + '\uninstall\*.*"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  for i := 0 to 9 do
  begin
    DeleteFile(ExpandConstant('{app}\unins00') + IntToStr(i) + '.dat');
    DeleteFile(ExpandConstant('{app}\unins00') + IntToStr(i) + '.exe');
    DeleteFile(ExpandConstant('{app}\unins00') + IntToStr(i) + '.msg');
  end;
  Log('JARVIS: previous uninstall data cleared; JARVIS.exe present: ' + IntToStr(Ord(FileExists(Exe))));
  for i := 1 to 40 do
  begin
    if not FileExists(Exe) then
      Break;
    if RenameFile(Exe, Exe + '.inst') then
    begin
      RenameFile(Exe + '.inst', Exe);
      Break;
    end;
    Sleep(500);
  end;
end;

// Shortcuts are made here instead of [Icons]: when Windows or an antivirus refuses to write a .lnk
// ("IPersistFile::Save ... 0x80070005"), the installation must still finish, just without that shortcut.
procedure MakeShortcut(const Path: String);
begin
  try
    if FileExists(Path) then
      DeleteFile(Path);
    CreateShellLink(Path, 'JARVIS', ExpandConstant('{app}\JARVIS.exe'), '', ExpandConstant('{app}'), '', 0, SW_SHOWNORMAL);
  except
    Log('Shortcut not created: ' + Path + ': ' + GetExceptionMessage);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MakeShortcut(ExpandConstant('{autoprograms}\JARVIS.lnk'));
    if WizardIsTaskSelected('desktopicon') then
      MakeShortcut(ExpandConstant('{autodesktop}\JARVIS.lnk'));
  end;
end;

