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
Name: "voicepack"; Description: "Hlas a rozpoznávání řeči i bez internetu (stáhne se teď, asi 550 MB)"; GroupDescription: "Stáhnout rovnou:"
Name: "netfix"; Description: "Povolit JARVIS ve firewallu (telefon, internet, Tailscale) – Windows se zeptá"; GroupDescription: "Stáhnout rovnou:"
Name: "omniroute"; Description: "OmniRoute: vlastní AI brána na tomhle PC (pro pokročilé, nainstaluje i Node.js)"; GroupDescription: "Pro pokročilé (mozek stačí API klíč):"; Flags: unchecked
Name: "ollama"; Description: "Ollama: offline AI na tvém PC (stáhne ~2 GB model)"; GroupDescription: "Pro pokročilé (mozek stačí API klíč):"; Flags: unchecked
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
Filename: "{app}\JARVIS.exe"; Parameters: "--fix-network"; Verb: "runas"; StatusMsg: "Povoluji JARVIS ve firewallu (Windows se zeptá)…"; Flags: shellexec waituntilterminated runhidden; Tasks: netfix; Check: not WizardSilent
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

// 3.12 Hlas a řeč offline: the voice (Piper, Czech) and the speech recogniser (Whisper small) downloaded during the
// installation – shown on its own page with progress, only when the box is ticked, never in a silent update. Pinned
// versions with SHA-256, so a changed or broken file is refused. Already there (an update): not downloaded again.
const
  WHISPER = 'https://huggingface.co/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120/';
  PIPER = 'https://huggingface.co/rhasspy/piper-voices/resolve/6b9cfaacb4fb2e02a9621227e3c1a48bec9710c3/cs/cs_CZ/jirka/medium/';

var
  DownloadPage: TDownloadWizardPage;
  Fetched, FetchedTo: TStringList;

function ModelsDir(): String;
begin
  Result := ExpandConstant('{userappdata}\JARVIS\models');
end;

procedure Want(const Url, Name, Sha, Dest: String);
begin
  if not FileExists(Dest) then
  begin
    DownloadPage.Add(Url, Name, Sha);
    Fetched.Add(Name);
    FetchedTo.Add(Dest);
  end;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Stahuji hlas a rozpoznávání řeči', 'Hlas JARVISe a rozpoznávání řeči, aby fungovaly i bez internetu. Chvíli to potrvá.', nil);
  Fetched := TStringList.Create;
  FetchedTo := TStringList.Create;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  W, P: String;
begin
  Result := True;
  if (CurPageID <> wpReady) or WizardSilent or not WizardIsTaskSelected('voicepack') then
    exit;
  W := ModelsDir() + '\whisper\faster-whisper-small\';
  P := ModelsDir() + '\piper\';
  DownloadPage.Clear;
  Fetched.Clear;
  FetchedTo.Clear;
  Want(WHISPER + 'model.bin', 'model.bin', '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671', W + 'model.bin');
  Want(WHISPER + 'config.json', 'config.json', 'b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828', W + 'config.json');
  Want(WHISPER + 'tokenizer.json', 'tokenizer.json', 'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab', W + 'tokenizer.json');
  Want(WHISPER + 'vocabulary.txt', 'vocabulary.txt', '34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913', W + 'vocabulary.txt');
  Want(PIPER + 'cs_CZ-jirka-medium.onnx', 'cs_CZ-jirka-medium.onnx', '9bc0b76bb8f26e1d542bf7ed2ce8a6c764605a5f6edcc7663bd637d0b684c5d9', P + 'cs_CZ-jirka-medium.onnx');
  Want(PIPER + 'cs_CZ-jirka-medium.onnx.json', 'cs_CZ-jirka-medium.onnx.json', '4486971d79354d2f6d376fdd74f90acc6beb4308ba64083cfb03765e2c25cec1', P + 'cs_CZ-jirka-medium.onnx.json');
  if Fetched.Count = 0 then
    exit;
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      // no internet / cancelled: JARVIS installs anyway; the voice and speech come over the internet until then
      Fetched.Clear;
      FetchedTo.Clear;
      if not DownloadPage.AbortedByUser then
        SuppressibleMsgBox('Hlas a rozpoznávání řeči se teď nepodařilo stáhnout (' + GetExceptionMessage + '). JARVIS se nainstaluje i tak – stáhnout je půjde později v Nastavení → Hlas.', mbInformation, MB_OK, IDOK);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure PlaceDownloads;
var
  i: Integer;
  Name, Dest: String;
begin
  for i := 0 to Fetched.Count - 1 do
  begin
    Name := Fetched[i];
    Dest := FetchedTo[i];
    ForceDirectories(ExtractFileDir(Dest));
    if not FileCopy(ExpandConstant('{tmp}\') + Name, Dest, False) then
      Log('Voice pack: could not place ' + Dest);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    PlaceDownloads;
    MakeShortcut(ExpandConstant('{autoprograms}\JARVIS.lnk'));
    if WizardIsTaskSelected('desktopicon') then
      MakeShortcut(ExpandConstant('{autodesktop}\JARVIS.lnk'));
  end;
end;

