; Single source of truth: VERSION.TXT at the project root. Update that file
; and re-run the build — every version-stamped field below is derived from it.
#define VersionFile FileOpen(AddBackslash(SourcePath) + "VERSION.TXT")
#define AppVer Trim(FileRead(VersionFile))
#expr FileClose(VersionFile)
#undef VersionFile

; CreateCustomForm (the uninstall dialog) takes four arguments from Inno Setup 6.6.0.
#if Ver < EncodeVer(6, 6, 0)
  #error This installer needs Inno Setup 6.6.0 or newer
#endif

[Setup]
AppId={{9A8B7C6D-4E3F-5B2A-0D1E-8F7G6H5I4J3K}
AppName=Smart Citizen
AppVersion={#AppVer}
AppPublisher=Osiris DevWorks, LLC
AppPublisherURL=https://github.com/Osiris-DevWorks/smart-citizen
DefaultDirName={localappdata}\Osiris DevWorks\Smart Citizen
DefaultGroupName=Smart Citizen
OutputDir=dist
OutputBaseFilename=SmartCitizen-{#AppVer}-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
DisableDirPage=no
AllowUNCPath=no
PrivilegesRequired=admin
SetupIconFile=assets\logo.ico
; Write a per-run install log to %TEMP%\Setup Log YYYY-MM-DD #NNN.txt.
; Critical for diagnosing the upgrade-uninstall race (see UnInstallOldVersion):
; without this, the WARNING from a WaitForUninstallToFinish timeout goes nowhere
; and a tester reporting "uninstall.exe was deleted" gives us nothing to grep.
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
SCDirectoryPrompt=Star Citizen Directory
SCDirectoryPromptDesc=Please specify your Star Citizen LIVE directory for automatic file detection.
SCDirectoryDefaultDesc=This is typically located at:
SCDirectoryDefaultPath=C:\Program Files\Roberts Space Industries\StarCitizen\LIVE

[InstallDelete]
; Clear previous install directory completely before installing new files
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "dist\SmartCitizen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Smart Citizen"; Filename: "{app}\SmartCitizen.exe"
Name: "{group}\{cm:UninstallProgram,Smart Citizen}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Smart Citizen"; Filename: "{app}\SmartCitizen.exe"

[Run]
Filename: "{app}\SmartCitizen.exe"; Description: "{cm:LaunchProgram,Smart Citizen}"; Flags: nowait postinstall skipifsilent
; The #211 in-app auto-update relaunch is not a [Run] entry. Setup runs [Run]
; entries that are not postinstall BEFORE it signals ssPostInstall, and
; WriteInstallerChoicesToRegistry runs at ssPostInstall, so an entry here
; started the app before its settings were written. CurStepChanged relaunches
; it after the writes instead.

[Code]
var
  SCDirectoryPage: TInputDirWizardPage;
  DataDirPage: TInputDirWizardPage;
  { 1.4.1: cache lives on a separate page so users can split the ~1.4 GB
    DataForge tree off the user-data folder (e.g. SSD for cache,
    OneDrive Documents for user.ini). Saved to HKCU\...\cache_dir;
    cleared on Reset so the app's default (%LOCALAPPDATA%\Smart Citizen)
    wins on resolution. }
  CacheDirPage: TInputDirWizardPage;
  { #180: Simple vs Advanced start mode. Radio page; the choice is written to
    HKCU\...\ui_mode in WriteInstallerChoicesToRegistry and the app reads it on
    first launch. Defaults to Simple, pre-selected from a prior install. }
  ModeChoicePage: TInputOptionWizardPage;
  { App UI/string language. Radio page anchored to wpWelcome so it's the very
    first page the user sees, before any of the built-in wizard pages. The
    choice is written to HKCU\...\selected_language (matching AppSettings.
    SELECTED_LANGUAGE) so the app opens in that language on first launch
    instead of defaulting to English until the user finds the Config tab's
    language selector. Options must stay in sync with the non-stub folders
    under languages/ (AppSettings.get_available_languages()). }
  LanguageChoicePage: TInputOptionWizardPage;
  { True when a saved selected_language value was found but didn't match any
    of the known LanguageChoicePage options below. Guards the always-write in
    WriteInstallerChoicesToRegistry: without it, an upgrade install whose
    saved value has fallen out of sync with this page's option list (e.g. a
    5th language shipped in the app but not added here yet) would silently
    overwrite the user's real saved value with 'english', since the page
    itself falls back to displaying English (index 0) for an unrecognized
    value. See #236 review discussion. }
  LanguageChoiceUnknownSaved: Boolean;
  { #357: set by the checkbox on the custom uninstall confirmation dialog
    (InitializeUninstall). False (the safe, non-destructive default) unless
    the user explicitly ticked "also delete all saved settings" -- read by
    CurUninstallStepChanged to decide between the normal cache-only cleanup
    and the full opt-in wipe (DeleteAllUserSettings). }
  DeleteAllSettingsChecked: Boolean;

const
  SCRegNode = 'Software\Osiris DevWorks\Smart Citizen';
  SCLegacyRegNode = 'Software\Osiris DevWorks\SC Localization Editor';
  { LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW: see ScChannelName. }
  ScChannelCount = 5;
  { Files and folders that prove a Star Citizen channel: see HasScGameData. }
  ScMarkerCount = 10;

function IsAutoUpdate(): Boolean;
begin
  { True when this install was spawned by the app's in-app auto-updater
    (#211), which passes /AUTOUPDATE=1 — see _launch_installer_and_quit in
    src/gui/main_window.py. Drives the [Run] entry that relaunches the app
    after a silent upgrade. }
  Result := ExpandConstant('{param:AUTOUPDATE|0}') = '1';
end;

function GetLocalCacheDefault(): String;
begin
  { Mirrors AppSettings.get_dataforge_cache_base() default for registry
    mode: %LOCALAPPDATA%\Smart Citizen. Channel/cache/dataforge nesting
    is added by the app at runtime. }
  Result := ExpandConstant('{%LOCALAPPDATA}\Smart Citizen');
end;

function GetCacheDir(): String;
var
  OverridePath: String;
begin
  { Override-aware, like GetDocumentsDir: the full wipe has to clean where the
    cache really lives, not just the %LOCALAPPDATA% default. }
  if RegQueryStringValue(HKCU, SCRegNode, 'cache_dir', OverridePath)
     and (OverridePath <> '') then
  begin
    Result := OverridePath;
    Exit;
  end;
  Result := GetLocalCacheDefault();
end;

function SuggestLocalDataDir(): String;
begin
  { Build a sensible default pointing at the local (non-OneDrive) profile.
    %USERPROFILE% is the real NTFS path; \Documents here is the junction
    that Windows keeps even when the shell's Personal has been redirected. }
  Result := ExpandConstant('{%USERPROFILE}\Documents\Smart Citizen');
end;

function IsOneDriveSegment(const Seg: String): Boolean;
var
  Low: String;
begin
  { Mirror of onedrive.py:_is_onedrive_segment. True for a path segment that
    names a OneDrive folder: bare "OneDrive" and the org variants
    "OneDrive - Contoso" / "OneDrive-Contoso", but NOT look-alikes like
    "OneDriveBackups". Keep this in sync with the app's detection so the
    installer and the app agree on what counts as OneDrive. }
  Low := Trim(LowerCase(Seg));
  Result := (Low = 'onedrive') or
            (Copy(Low, 1, Length('onedrive - ')) = 'onedrive - ') or
            (Copy(Low, 1, Length('onedrive-')) = 'onedrive-');
end;

function PathUnderRoot(const Child, Root: String): Boolean;
var
  C, R: String;
begin
  { Prefix test that can't false-match a sibling: "...\OneDriveStuff" must NOT
    register as under "...\OneDrive". Append a backslash to both sides before
    comparing (mirror of onedrive.py's norm == root or norm.startswith(root + sep)).
    Empty Root never matches — an unset env var must not match everything. }
  Result := False;
  if (Child = '') or (Root = '') then
    Exit;
  C := AddBackslash(LowerCase(RemoveBackslash(Child)));
  R := AddBackslash(LowerCase(RemoveBackslash(Root)));
  Result := (Pos(R, C) = 1);
end;

function IsPathOnOneDrive(const Path: String): Boolean;
var
  Roots: array[0..2] of String;
  i, P: Integer;
  Norm, Remaining, Seg: String;
begin
  { Mirror of onedrive.py:is_onedrive_path. Two independent signals, either
    sufficient:
      1. Path is at/under a OneDrive root from the environment
         (%OneDrive% / %OneDriveConsumer% / %OneDriveCommercial%) — the
         precise signal. Empty vars are skipped (unset must not match all).
      2. Path contains a "OneDrive" path segment — a fallback that catches
         org folders and contexts where the env var isn't set.
    Used by NextButtonClick to warn on ANY chosen path (a hand-browsed
    OneDrive subfolder or a pre-filled OneDrive override), not just the
    shell Documents default that IsDocsOnOneDrive steers. }
  Result := False;
  if Path = '' then
    Exit;

  { Windows takes '/' as a separator too, and the data-folder edit box passes
    on whatever was typed. Compare with '\' only (the app's check gets this
    from os.path.normpath). }
  Norm := Path;
  StringChangeEx(Norm, '/', '\', True);

  Roots[0] := GetEnv('OneDrive');
  Roots[1] := GetEnv('OneDriveConsumer');
  Roots[2] := GetEnv('OneDriveCommercial');
  for i := 0 to 2 do
  begin
    if PathUnderRoot(Norm, Roots[i]) then
    begin
      Result := True;
      Exit;
    end;
  end;

  { Segment fallback: split on '\' and test each component. }
  Remaining := Norm;
  while Remaining <> '' do
  begin
    P := Pos('\', Remaining);
    if P = 0 then
    begin
      Seg := Remaining;
      Remaining := '';
    end
    else
    begin
      Seg := Copy(Remaining, 1, P - 1);
      Remaining := Copy(Remaining, P + 1, MaxInt);
    end;
    if IsOneDriveSegment(Seg) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsDocsOnOneDrive(): Boolean;
var
  DocsPath: String;
begin
  { Read the invoking user's Documents shell-folder path. When Windows has
    folder-redirected Documents into OneDrive (the default on most OneDrive
    installs now), the path runs through a OneDrive folder: "OneDrive" for a
    personal account, "OneDrive - Contoso" for a work or school one. Cache
    extraction + 50,000-file rmtree under an actively-synced OneDrive tree is
    3-5x slower and routinely fails with WinError 5 — worth warning the user
    and offering a local-only alternative. IsPathOnOneDrive does the
    matching, so this pre-fill, the Next-click warning and the app all agree
    on what counts as OneDrive. }
  Result := False;
  if RegQueryStringValue(HKCU,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    'Personal', DocsPath) then
    Result := IsPathOnOneDrive(DocsPath);
end;

function HasVersionedAppSegment(const Path: String): Boolean;
var
  Remaining, Seg, Low, Rest: String;
  P: Integer;
begin
  { True if any path segment is the app name followed by a version-like
    token, e.g. 'SmartCitizen-v1.4.1' or 'Smart Citizen 1.4.1'. The data and
    cache defaults have always been the unversioned 'Smart Citizen', so a
    version suffix only ever comes from an old install layout, never a real
    folder choice. Case-insensitive; checks every segment so a versioned
    segment mid-path is caught too. Issue #120. }
  Result := False;
  Remaining := Path;
  while Remaining <> '' do
  begin
    P := Pos('\', Remaining);
    if P = 0 then
    begin
      Seg := Remaining;
      Remaining := '';
    end
    else
    begin
      Seg := Copy(Remaining, 1, P - 1);
      Remaining := Copy(Remaining, P + 1, MaxInt);
    end;
    Low := LowerCase(Seg);
    if Pos('smartcitizen', Low) = 1 then
      Rest := Copy(Low, Length('smartcitizen') + 1, MaxInt)
    else if Pos('smart citizen', Low) = 1 then
      Rest := Copy(Low, Length('smart citizen') + 1, MaxInt)
    else
      Continue;
    { Strip a leading separator / 'v' so '-v1.4.1', ' 1.4.1', '_v2.0' match,
      while 'Smart Citizen' (no suffix) and 'SmartCitizenVault' do not. }
    while (Rest <> '') and ((Rest[1] = ' ') or (Rest[1] = '-') or
          (Rest[1] = '_') or (Rest[1] = 'v')) do
      Rest := Copy(Rest, 2, MaxInt);
    if (Rest <> '') and (Rest[1] >= '0') and (Rest[1] <= '9') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsStalePrefill(const Path: String): Boolean;
begin
  { A saved data/cache path should NOT be used as the wizard prefill when it
    no longer exists on disk, or it points at a versioned app folder left
    over from an old install. Either way the page falls back to the default.
    Defensive guard for issue #120: the reported stale 'SmartCitizen 1.4.1'
    value was confirmed to live in the SC-install-path keys (fixed in #119),
    but the data/cache pages read separate keys with no equivalent check, so
    this hardens them against any stale versioned value reaching the prefill. }
  Result := (not DirExists(Path)) or HasVersionedAppSegment(Path);
end;

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

procedure ClearStaleUninstallEntry();
var
  sRegPath: String;
begin
  { Remove zombie registry entries that point at a non-existent unins000.exe.
    Background: when a user's previous install lived under a non-default path
    (e.g. Documents\Smart Citizen\) and the folder was manually deleted or
    moved without running the uninstaller, Windows keeps the Uninstall
    registry entry — and "Installed Apps" on Win10/11 then shows the app
    with an Uninstall button that fails ("Windows cannot find …\unins000.exe").
    Left alone, the entry also blocks our GetUninstallString() / IsUpgrade()
    flow from doing the right thing. Clearing both HKLM and HKCU variants
    is safe: the install about to run will recreate the entry cleanly. }
  sRegPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1';
  RegDeleteKeyIncludingSubkeys(HKLM, sRegPath);
  RegDeleteKeyIncludingSubkeys(HKCU, sRegPath);
  Log('Cleared stale uninstall registry entry (unins000.exe was missing)');
end;

function WaitForUninstallerCleanup(const UninstallerExe: String; MaxSeconds: Integer): Boolean;
var
  Elapsed: Integer;
begin
  { Inno Setup's silent uninstaller copies itself to %TEMP%\_iu*.tmp and the
    original exits immediately — so the Exec() that launched it returns long
    before the temp copy has finished its work.

    Signal choice matters here, and the obvious one is WRONG: the AppId_is1
    registry key is NOT the uninstaller's last act. Inno undoes the install
    log in reverse order, and the key — written last at install time — is
    removed within the first moments of the uninstall. A previous version of
    this wait polled that key and routinely returned in under half a second
    while file cleanup ran on for seconds more, letting the old uninstaller
    delete the NEW unins000.exe the install had just written (2.0 test-build
    log: key gone <0.5 s after Exec; new unins000.exe written at +0.4 s,
    gone by +6 s).

    The on-disk uninstaller exe is the right signal: deleting itself is part
    of the temp copy's FINAL self-cleanup, after all file deletion. A short
    settle after it disappears covers the trailing app-dir removal and
    registry deletion. Only called for old installs in a DIFFERENT directory
    (see UnInstallOldVersion), so polling the old exe can't race our own
    InstallDelete. }
  Elapsed := 0;
  while Elapsed < MaxSeconds * 4 do
  begin
    if not FileExists(UninstallerExe) then
    begin
      Sleep(1000);  { settle: trailing dir-removal + registry cleanup }
      Result := True;
      Exit;
    end;
    Sleep(250);
    Inc(Elapsed);
  end;
  Result := False;
end;

function UnInstallOldVersion(): Integer;
var
  sUnInstallString: String;
  OldAppDir: String;
  NewAppDir: String;
  iResultCode: Integer;
  SavedStatus: String;
  SavedStyle: TNewProgressBarStyle;
begin
  { Return Values:
    1 - uninstall string is empty
    2 - error executing the UnInstallString
    3 - successfully executed the UnInstallString
    4 - uninstall string found but the unins000.exe doesn't exist (zombie
        entry from a manual folder deletion) — cleared the registry entry
        so the new install can register fresh.
    5 - same-directory upgrade: old uninstaller deliberately NOT run. }

  Result := 0;

  { get the uninstall string of the old app }
  sUnInstallString := GetUninstallString();
  if sUnInstallString = '' then begin
    Result := 1;
    Exit;
  end;

  sUnInstallString := RemoveQuotes(sUnInstallString);

  { Zombie-entry guard: if the recorded unins000.exe isn't on disk, running
    Exec() against it would fail silently and leave the registry entry
    dangling forever (plus Windows' "Installed Apps" would keep offering a
    broken Uninstall button). Nuke the registry entry and let the new
    install write a fresh one. Addresses the
      "Windows cannot find …\unins000.exe"
    error users report after a partial/manual removal of a custom-path
    install. }
  if not FileExists(sUnInstallString) then begin
    ClearStaleUninstallEntry();
    Result := 4;
    Exit;
  end;

  // Same-directory upgrade: SKIP the old uninstaller entirely. Running it
  // is what created the recurring "uninstaller is missing" failure: the
  // silent uninstaller detaches a temp copy whose file cleanup runs
  // concurrently with our [InstallDelete] + [Files] phases, deleting old
  // files by ABSOLUTE PATH — the same paths the new install is writing.
  // Its final self-cleanup then removes the app dir's unins000.exe, which
  // by that point is the NEW uninstaller (2.0 test-build log: new
  // unins000.exe written at 20:32:19.355, install succeeded 20:32:25.186,
  // file gone 4 ms later).
  //
  // The old uninstaller adds nothing in the same-dir case:
  //   - old files     -> the InstallDelete filesandordirs entry wipes them
  //   - uninstall key -> same AppId; the new install overwrites it
  //   - icons         -> same group/desktop names; recreated by [Icons]
  //   - cache cleanup -> CleanCachedData() runs install-side at ssInstall
  // Only an old install at a DIFFERENT directory needs its uninstaller
  // run, because InstallDelete can't reach files outside the new app dir.
  // (Line comments here on purpose — the install-dir constant's curly
  // syntax closes Pascal block comments early.)
  OldAppDir := RemoveBackslash(ExtractFileDir(sUnInstallString));
  NewAppDir := RemoveBackslash(ExpandConstant('{app}'));
  if CompareText(OldAppDir, NewAppDir) = 0 then begin
    Log('Same-directory upgrade (' + NewAppDir + '): skipping old uninstaller; InstallDelete clears the directory and the new install rewrites the uninstall key.');
    Result := 5;
    Exit;
  end;

  Log('Old install found at different directory (' + OldAppDir + '); running its uninstaller: ' + sUnInstallString);

  { Distinct upgrade-uninstall step: flip the wizard's status label to
    "Uninstalling previous version..." and run the progress bar in marquee
    mode while the old uninstaller does its work. Without this UX cue,
    users saw the install page sit silently for 5–30s and assumed the
    installer had hung. }
  SavedStatus := WizardForm.StatusLabel.Caption;
  SavedStyle := WizardForm.ProgressGauge.Style;
  WizardForm.StatusLabel.Caption := 'Uninstalling previous version...';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  WizardForm.Update;

  if Exec(sUnInstallString, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
  begin
    Log('Old uninstaller launcher exited (code ' + IntToStr(iResultCode) + '); waiting for its temp copy to finish cleanup.');
    { Wait for the detached temp copy to finish before install proceeds.
      Watches the old unins000.exe disappear (its deletion is part of the
      temp copy's FINAL self-cleanup) — see WaitForUninstallerCleanup for
      why the registry key is the wrong signal. 180 s covers slow-disk +
      actively-syncing-OneDrive + Defender-on-access environments. When
      the timeout *does* fire, surface a wizard error dialog instead of
      only logging — a log-only warning meant users discovered the broken
      state days later when Apps & Features had no entry.
      SuppressibleMsgBox: a /SUPPRESSMSGBOXES run (the in-app auto-updater
      of #211) only logs the warning, because it is a "may happen" notice.
      If the new unins000.exe really is deleted, the ssPostInstall check in
      CurStepChanged still shows its error box, which is not suppressible. }
    if WaitForUninstallerCleanup(sUnInstallString, 180) then
      Log('Old uninstaller cleanup finished.')
    else
    begin
      Log('WARNING: timed out waiting for old uninstaller to finish (180s). The new install may produce a broken uninstaller; user should uninstall + reinstall manually if the Apps & Features entry is missing.');
      SuppressibleMsgBox('The previous version''s uninstaller did not finish within 3 minutes.' + #13#10 + #13#10 +
             'The install will continue, but the new uninstaller file (unins000.exe) may be deleted by the old uninstaller''s delayed cleanup. If that happens, Smart Citizen will install successfully but will not appear in Apps & Features.' + #13#10 + #13#10 +
             'If you later cannot uninstall Smart Citizen, re-run this installer and choose the Uninstall option, or delete the install folder manually.' + #13#10 + #13#10 +
             'Closing other apps (especially OneDrive sync, antivirus scans, and the Search Indexer) before the install can avoid this.',
             mbError, MB_OK, IDOK);
    end;
    Result := 3;
  end
  else
  begin
    Log('WARNING: failed to execute old uninstaller (' + sUnInstallString + ').');
    Result := 2;
  end;

  { Restore the wizard for the install phase. }
  WizardForm.StatusLabel.Caption := SavedStatus;
  WizardForm.ProgressGauge.Style := SavedStyle;
  WizardForm.Update;
end;

function GetDocumentsBase(): String;
begin
  if not RegQueryStringValue(HKCU,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    'Personal', Result) then
  begin
    Result := ExpandConstant('{userdocs}');
  end;
end;

function GetDefaultDocumentsDir(): String;
begin
  { The app's default data folder when no user_data_dir override is set. }
  Result := GetDocumentsBase() + '\Smart Citizen';
end;

function GetLegacyDocumentsDir(): String;
begin
  { The pre-0.9 data folder, from before the rebrand. }
  Result := GetDocumentsBase() + '\SC Localization Editor';
end;

function GetDocumentsDir(): String;
var
  OverridePath: String;
begin
  { Match the app's resolution order (AppSettings.get_user_data_dir):
      1. user_data_dir registry override — set when the user picked a
         non-Documents folder during install (OneDrive escape) or via the
         in-app data dir setting. If the app is storing cache here, the
         uninstaller MUST clean here too — otherwise stale 2GB+ caches
         survive uninstall.
      2. userdocs \Smart Citizen — the default. }
  if RegQueryStringValue(HKCU,
    SCRegNode,
    'user_data_dir', OverridePath) and (OverridePath <> '') then
  begin
    Result := OverridePath;
    Exit;
  end;
  Result := GetDefaultDocumentsDir();
end;

procedure MigrateUserDocsFolder();
var
  DocsBase, OldDir, NewDir: String;
begin
  { Rebrand: rename Documents\SC Localization Editor\ → Documents\Smart Citizen\
    if the old folder exists and the new one does not. User data (user.ini,
    backups, cache) moves with the rename — no copy required.
    The notice is a SuppressibleMsgBox: the rename happens whatever the
    click, so a /SUPPRESSMSGBOXES run (the in-app auto-updater, #211) logs
    it below instead of stopping on an OK box. }
  DocsBase := GetDocumentsBase();
  OldDir := GetLegacyDocumentsDir();
  NewDir := GetDefaultDocumentsDir();
  if DirExists(OldDir) and not DirExists(NewDir) then
  begin
    SuppressibleMsgBox('Your user data folder will be renamed as part of this update:' + #13#10 + #13#10 +
           '  ' + OldDir + #13#10 +
           '  →  ' + NewDir + #13#10 + #13#10 +
           'Your custom edits, backups, and cached files will move with it — nothing is lost.',
           mbInformation, MB_OK, IDOK);
    Log('Renaming user data folder: ' + OldDir + ' -> ' + NewDir);
    if not RenameFile(OldDir, NewDir) then
      Log('WARNING: rename failed; data remains at old location');
  end;
end;

function ScChannelName(const I: Integer): String;
begin
  { Channel I of ScChannelCount. Keep in step with install_scanner.SC_CHANNELS. }
  case I of
    0: Result := 'LIVE';
    1: Result := 'PTU';
    2: Result := 'EPTU';
    3: Result := 'HOTFIX';
  else
    Result := 'TECH-PREVIEW';
  end;
end;

{ Defined with the other delete-safety checks, further down. }
function UnsafeDeleteRootReason(const RawRoot: String): String; forward;

function LooksLikeScCache(const Dir: String): Boolean;
var
  i: Integer;
begin
  { True when Dir holds something only a Smart Citizen cache holds, so a folder
    named "cache" that belongs to another program is never taken for ours. The
    name is generic and the data folder can be any folder the user picked. The
    three marks cover every layout the app has written:
      base.ini         the cached global source. It sits in a per-channel cache
                       (<data folder>\<channel>\cache) and in the pre-0.9.3
                       flat cache (<data folder>\cache), with the enhancement
                       INIs next to it.
      dataforge        the pre-0.9.3 flat cache only, which held the DataForge
                       XML tree directly (<data folder>\cache\dataforge) until
                       1.x moved it to %LOCALAPPDATA%.
      <channel>\cache  a DataForge cache folder, the default under
                       %LOCALAPPDATA% or one chosen in the installer or the
                       Config tab. It holds <cache folder>\<channel>\cache\
                       dataforge, never a dataforge folder directly under it.
    An empty or missing folder, and one holding anything else, is not ours. }
  Result := False;
  if not DirExists(Dir) then
    Exit;
  Result := FileExists(Dir + '\base.ini') or DirExists(Dir + '\dataforge');
  for i := 0 to ScChannelCount - 1 do
    if not Result then
      Result := DirExists(Dir + '\' + ScChannelName(i) + '\cache');
end;

procedure CleanPerChannelCaches(UserDataDir: String);
var
  i: Integer;
  CachePath, Reason: String;
  Deleted: Boolean;
begin
  { Per-channel layout (0.9.3+): each Star Citizen channel has its own
    user data subtree at Documents\Smart Citizen\<channel>\. Only \cache
    is disposable — \backups (the user's global.ini safety net) and
    user.ini (their customizations) must survive both install and
    uninstall, so we delete \cache per channel and leave the rest alone.

    Logs the path tried, the DelTree return value, and whether the
    directory still exists afterwards. Surfaces silent failures (locked
    files under OneDrive sync / Defender real-time scan) in the install
    log so users reporting "cache wasn't removed" can be diagnosed.

    The data folder can be any folder the user picked, and this runs on every
    install, upgrade and auto-update with nobody to ask. So it first asks
    UnsafeDeleteRootReason, and does nothing (with the reason in the log, never
    a dialog) in a folder that is not safe to delete in: a whole drive,
    Documents, a folder holding the Star Citizen install, and so on. }
  Reason := UnsafeDeleteRootReason(UserDataDir);
  if Reason <> '' then
  begin
    Log('Not cleaning per-channel caches under ' + UserDataDir + ' (' + Reason + ').');
    Exit;
  end;
  for i := 0 to ScChannelCount - 1 do
  begin
    CachePath := UserDataDir + '\' + ScChannelName(i) + '\cache';
    if DirExists(CachePath) then
    begin
      Log('Deleting per-channel cache: ' + CachePath);
      Deleted := DelTree(CachePath, True, True, True);
      if not Deleted then
        Log('WARNING: DelTree returned false for ' + CachePath);
      if DirExists(CachePath) then
        Log('WARNING: cache path still exists after DelTree: ' + CachePath +
            ' (likely a file is locked by OneDrive sync, Windows Defender, ' +
            'or the Search Indexer — close those processes and retry the uninstaller)');
    end
    else
    begin
      Log('Per-channel cache absent (nothing to delete): ' + CachePath);
    end;
  end;
end;

procedure CleanCachedData();
var
  UserDataDir, LegacyCache, Reason: String;
begin
  UserDataDir := GetDocumentsDir();
  if DirExists(UserDataDir) then
  begin
    { Nothing here is deleted unless the folder is safe to delete in. The Config
      tab lets the user pick a whole drive, and this runs on every install,
      upgrade and auto-update, so "D:\" would have lost D:\cache. Silent, like
      the cleaning itself: the reason goes to the log. }
    Reason := UnsafeDeleteRootReason(UserDataDir);
    if Reason <> '' then
    begin
      Log('Not cleaning cached data under ' + UserDataDir + ' (' + Reason + ').');
      Exit;
    end;
    Log('Cleaning cached data from: ' + UserDataDir);
    { Current layout — delete \cache under each channel subtree. }
    CleanPerChannelCaches(UserDataDir);
    { Defensive: pre-0.9.3 flat layout kept cache at \Smart Citizen\cache\.
      The channel migrator runs at app launch and should have moved this
      already, but if a user is upgrading from a state where the migrator
      never ran (e.g. they uninstalled before first launching 0.9.3+),
      mop it up here. Only when it holds a Smart Citizen cache: "cache" is
      a generic name, and the data folder can be any folder the user picked. }
    LegacyCache := UserDataDir + '\cache';
    if DirExists(LegacyCache) then
    begin
      if LooksLikeScCache(LegacyCache) then
      begin
        Log('Deleting legacy flat-layout cache: ' + LegacyCache);
        DelTree(LegacyCache, True, True, True);
      end
      else
        Log('Leaving ' + LegacyCache + ' alone: it holds no Smart Citizen cache (no base.ini, dataforge folder or channel cache).');
    end;
  end;
end;

{ Persistence contract (#172): the user's data-folder choice must survive
  uninstall + reinstall. It does so by construction —
    - user_data_dir is written to the LIVE node (Osiris DevWorks\Smart Citizen)
      via RegWriteStringValue in WriteInstallerChoicesToRegistry, NOT via a
      Registry-section entry, so Inno's own uninstaller has no value to drop;
    - the only code path that deletes the live node is DeleteAllUserSettings,
      reached when the user ticks "Also delete all saved settings" (#357),
      so every other uninstall leaves it alone;
    - InitializeWizard pre-fills user_data_dir on the next install.
  The real risk vector is a FUTURE change adding live-node deletion to the
  uninstall step (see CurUninstallStepChanged). A former CleanRegistrySettings()
  helper that key-deleted a whole node lived here and was dead code; it was
  removed deliberately so its wipe pattern can't be copied and retargeted at
  the live node. Do not add node/value deletion to any other uninstall path:
  the #357 opt-in is the one deliberate exception. }

{ Defined with the other SC path checks, further down. }
function IsValidSCRoot(const Path: String): Boolean; forward;

procedure WriteInstallerChoicesToRegistry();
var
  RegPath: String;
  FinalPath: String;
  SCRoot: String;
  DataDir: String;
  DocsDefault: String;
  CacheDir: String;
  CacheDefault: String;
begin
  { Persist the user's choices from the installer wizard pages
    (SC install dir + Smart Citizen data folder) into the registry
    so the app reads them on first launch. Called from
    CurStepChanged at ssPostInstall — AFTER files have been copied
    so ForceDirectories on a custom data folder doesn't race the
    install itself. }

  { SC directory: written to BOTH the new (Smart Citizen) and legacy
    (SC Localization Editor) registry nodes. The new node survives
    the app's migrate_registry_appname() — which deletes the legacy
    subtree after copying values across. The legacy write is a compat
    fallback for very old app versions that haven't been launched
    yet to perform their own migration; cheap and keeps downgrade
    paths working. }
  FinalPath := SCDirectoryPage.Values[0];
  if FinalPath <> '' then
  begin
    RegPath := SCRegNode;
    RegWriteStringValue(HKCU, RegPath, 'sc_directory', FinalPath);
    RegWriteStringValue(HKCU, RegPath, 'game_install_path', FinalPath);
    { Write sc_install_root (the folder that holds the channel folders) so a
      reinstall with a changed SC path doesn't leave the stale root from a
      prior migration winning over the freshly chosen directory. The page
      normally holds a channel folder, whose parent is the root. It can also
      hold the root itself (a saved root is pre-filled unchanged, or the user
      types one), and then its parent is the wrong folder. }
    if IsValidSCRoot(FinalPath) then
      SCRoot := RemoveBackslashUnlessRoot(FinalPath)
    else
      SCRoot := ExtractFileDir(RemoveBackslash(FinalPath));
    RegWriteStringValue(HKCU, RegPath, 'sc_install_root', SCRoot);
    RegWriteStringValue(HKCU,
      SCLegacyRegNode,
      'sc_directory', FinalPath);
    Log('Saved sc_directory to registry (Smart Citizen + legacy nodes): ' + FinalPath);
  end;

  { Persist the data folder choice. The page is always shown in 1.3.0+,
    so every install reaches this branch. Comparison rules:
      - Empty field, or value equal to the natural Documents default:
        clear the override so the app's dynamic Documents resolution
        wins on every launch (matches the in-app Reset behavior in
        AppSettings.set_user_data_dir(None)). Keeps the registry tidy
        for users who never wanted a custom path.
      - Anything else: write user_data_dir. Also clear the legacy
        camelCase 'UserDataDir' alias if present so the app reads the
        canonical value. ForceDirectories ensures the chosen folder
        exists by the time the app first launches.
    Writes are scoped to the NEW (Smart Citizen) registry node — the
    app's migrate_registry_appname() preserves it across rebrand
    migrations. }
  DataDir := DataDirPage.Values[0];
  DocsDefault := GetDefaultDocumentsDir();
  if (DataDir = '') or (CompareText(DataDir, DocsDefault) = 0) then
  begin
    RegDeleteValue(HKCU,
      SCRegNode, 'user_data_dir');
    RegDeleteValue(HKCU,
      SCRegNode, 'UserDataDir');
    Log('User chose default Documents folder; cleared user_data_dir override.');
  end
  else
  begin
    RegWriteStringValue(HKCU,
      SCRegNode,
      'user_data_dir', DataDir);
    RegDeleteValue(HKCU,
      SCRegNode, 'UserDataDir');
    ForceDirectories(DataDir);
    Log('Saved user_data_dir to registry: ' + DataDir);
  end;

  { 1.4.1+: persist the cache folder choice. Same comparison rule as
    user_data_dir — clear the override when the user accepted the
    %LOCALAPPDATA%\Smart Citizen default so the app's runtime resolver
    stays in charge. Otherwise write cache_dir and pre-create the
    directory. }
  CacheDir := CacheDirPage.Values[0];
  CacheDefault := GetLocalCacheDefault();
  if (CacheDir = '') or (CompareText(CacheDir, CacheDefault) = 0) then
  begin
    RegDeleteValue(HKCU,
      SCRegNode, 'cache_dir');
    Log('User chose default cache folder; cleared cache_dir override.');
  end
  else
  begin
    RegWriteStringValue(HKCU,
      SCRegNode,
      'cache_dir', CacheDir);
    ForceDirectories(CacheDir);
    Log('Saved cache_dir to registry: ' + CacheDir);
  end;

  { #180: persist the Simple/Advanced start mode. Always written (not just on
    a non-default) so a fresh install opens in the user's chosen mode rather
    than relying on the app's "simple when unset" fallback. Honors the #172
    persistence contract: this only writes the live node; nothing is deleted
    on uninstall. }
  if ModeChoicePage.SelectedValueIndex = 1 then
    RegWriteStringValue(HKCU,
      SCRegNode, 'ui_mode', 'advanced')
  else
    RegWriteStringValue(HKCU,
      SCRegNode, 'ui_mode', 'simple');
  Log('Saved ui_mode to registry.');

  { App UI/string language, matching AppSettings.SELECTED_LANGUAGE. Always
    written (not just on a non-English choice) so a fresh install opens in
    the chosen language rather than relying on the app's English fallback.
    Values here must stay in sync with the folder names under languages/.

    Exception: skip the write when the saved value didn't match any option
    this page knows about (LanguageChoiceUnknownSaved) AND the selection is
    still sitting at the pre-selected default (index 0) — the page falls
    back to displaying English in that case, and an always-write would
    silently downgrade the user's real (just-unrecognized) language back to
    English, both on an interactive upgrade and on a silent auto-update
    install where nobody sees the page to correct it. The index-0 check
    matters: on an INTERACTIVE upgrade the user still sees the page and can
    actively move the selection off English to a real choice, and that
    explicit pick must win — the flag only describes the pre-selection
    state, not anything the user did afterward. Worst case with the guard:
    a user who deliberately re-picks English while their saved value is
    unknown stays on the unknown value (the safe direction — they can
    switch in-app, and this never destroys a value it doesn't understand). }
  if LanguageChoiceUnknownSaved and (LanguageChoicePage.SelectedValueIndex = 0) then
    Log('Skipped rewriting selected_language: saved value matched no known option and selection was left at the default, left unchanged.')
  else
  begin
    case LanguageChoicePage.SelectedValueIndex of
      1: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'french');
      2: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'portuguese_br');
      3: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'spanish');
      4: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'japanese');
      5: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'chinese');
      6: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'italian');
      7: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'german');
      8: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'turkish');
      9: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'korean');
      10: RegWriteStringValue(HKCU,
           SCRegNode, 'selected_language', 'chinese_traditional');
    else
      RegWriteStringValue(HKCU,
        SCRegNode, 'selected_language', 'english');
    end;
    Log('Saved selected_language to registry.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep=ssInstall) then
  begin
    if (IsUpgrade()) then
    begin
      UnInstallOldVersion();
    end;

    { Rebrand migration: rename Documents\SC Localization Editor\ to
      Documents\Smart Citizen\ before we touch any cached data. }
    MigrateUserDocsFolder();

    { Clear cached data but preserve registry settings (source paths, preferences, etc.) }
    CleanCachedData();
  end;

  if (CurStep = ssPostInstall) then
  begin
    { Persist wizard-page choices (sc_directory + user_data_dir) to the
      registry. Previously this lived in a procedure named
      `CurFinished(LastStep: TSetupStep)` — NOT a real Inno Setup event
      callback name (Inno doesn't support that signature) — so the
      whole block silently never ran. Users who customized the data
      folder in the installer would see Documents\Smart Citizen on
      first launch instead of their pick. Discovered post-1.3.0 release
      after a user reported the data-dir choice not carrying over. }
    WriteInstallerChoicesToRegistry();

    // #211 in-app auto-update: relaunch Smart Citizen now that its settings
    // are in the registry. Gated on the /AUTOUPDATE=1 switch the app passes,
    // so manual silent installs are unaffected. This used to be a [Run]
    // entry, but Setup runs those before ssPostInstall, so the app started
    // before the writes above. ExecAsOriginalUser is the runasoriginaluser
    // flag that entry had: the installer runs elevated, and without it the
    // relaunched app would run as admin (and write user.ini / caches with
    // admin ownership). It sits ahead of the unins000.exe check below, so a
    // failure box there never delays the relaunch.
    if IsAutoUpdate() then
    begin
      if not ExecAsOriginalUser(ExpandConstant('{app}\SmartCitizen.exe'), '',
                                ExpandConstant('{app}'), SW_SHOWNORMAL,
                                ewNoWait, ResultCode) then
        Log('WARNING: could not relaunch Smart Citizen after the auto-update (code ' + IntToStr(ResultCode) + ').');
    end;

    // Catch-all sanity check: by ssPostInstall, Inno has written its
    // generated uninstaller to the install dir. If it isn't there,
    // something removed it between [Files] completion and now — most
    // likely the upgrade-uninstall race (WaitForUninstallToFinish
    // timeout fired and the old uninstaller's temp copy nuked our new
    // one) or a Smart App Control / Defender quarantine of the unsigned
    // uninstaller binary. Tell the user explicitly rather than letting
    // them discover it days later when Apps & Features has no entry.
    // The install itself is kept — the app works fine without the
    // uninstaller; only removal is affected.
    // Using // line comments here rather than block comments because the
    // Inno constant syntax below (curly-brace form) closes Pascal block
    // comments early — both block forms in Pascal have non-nesting
    // terminators and are tripped by literal references to that syntax.
    // Deliberately a plain MsgBox, so /SUPPRESSMSGBOXES does not hide it:
    // it reports a failure that has already happened and that the user
    // must act on, and the setup log in %TEMP% is otherwise the only
    // trace. It has only an OK button, so it cannot change what Setup
    // does. The in-app auto-updater (#211) runs /SILENT, so the user who
    // just answered its UAC prompt sees the progress window and this box.
    // It never delays that update's relaunch: the app is started above,
    // before this check.
    if not FileExists(ExpandConstant('{app}\unins000.exe')) then
    begin
      Log('ERROR: unins000.exe missing from {app} post-install. Install completed but uninstall is broken.');
      MsgBox('Smart Citizen installed successfully, but the uninstaller file (unins000.exe) is missing from:' + #13#10 + #13#10 +
             '  ' + ExpandConstant('{app}') + #13#10 + #13#10 +
             'Smart Citizen will not appear in Apps & Features. The app itself works normally — only uninstall is affected.' + #13#10 + #13#10 +
             'Likely causes:' + #13#10 +
             '  - Windows Smart App Control or Defender quarantined the unsigned uninstaller' + #13#10 +
             '    (check Windows Security -> Protection history)' + #13#10 +
             '  - A previous version''s uninstaller finished cleanup after this install wrote its files' + #13#10 + #13#10 +
             'To remove Smart Citizen later: re-run this installer and choose the Uninstall option, or delete the install folder manually.',
             mbError, MB_OK);
    end;
  end;
end;

{ ---- #357: opt-in "Also delete all saved settings" ---------------------- }

function CanonDir(const P: String): String;
begin
  { The folder Windows will actually touch: slashes turned into backslashes,
    dot segments resolved, trailing dots/spaces and the last backslash dropped.
    Every comparison below uses this form. }
  Result := P;
  StringChangeEx(Result, '/', '\', True);
  Result := RemoveBackslash(ExpandFileName(Trim(Result)));
end;

function IsAbsoluteDir(const P: String): Boolean;
var
  S: String;
begin
  S := Trim(P);
  StringChangeEx(S, '/', '\', True);
  Result := ((Length(S) >= 3) and (Copy(S, 2, 2) = ':\')) or (Copy(S, 1, 2) = '\\');
end;

function SameDir(const A, B: String): Boolean;
begin
  { GetShortName maps a long name and its 8.3 alias (DOCUME~1) to one string. }
  Result := (A <> '') and (B <> '') and
            ((CompareText(CanonDir(A), CanonDir(B)) = 0) or
             (CompareText(GetShortName(CanonDir(A)), GetShortName(CanonDir(B))) = 0));
end;

function LongPath(const Dir: String): String;
begin
  { \\?\ lifts the 260-character limit that Setup otherwise has, and DataForge
    cache paths run past it. Dir must already be canonical (CanonDir), because
    Windows does not tidy a \\?\ path. }
  if Copy(Dir, 1, 2) = '\\' then
    Result := '\\?\UNC\' + Copy(Dir, 3, Length(Dir))
  else
    Result := '\\?\' + Dir;
end;

function IsLinkDir(const Dir: String): Boolean;
var
  FR: TFindRec;
begin
  { A junction or symbolic link (FILE_ATTRIBUTE_REPARSE_POINT). Windows may not
    let the uninstaller see inside one, so its contents cannot be checked. }
  Result := False;
  if FindFirst(Dir, FR) then
  try
    Result := (FR.Attributes and $400) <> 0;
  finally
    FindClose(FR);
  end;
end;

function HasScGameData(const Dir: String): Boolean;
var
  i: Integer;
  Marker: String;
begin
  { Anything a real Star Citizen channel keeps, even after its game data is
    deleted. Keep in step with install_scanner.SC_CHANNEL_MARKERS. USER (the
    player's keybinds and settings), ScreenShots, logbackups and Game.log are
    extra here: they are the player's own data, which outlives the game files.
    None of these ever appear in Smart Citizen's own folders. }
  Result := False;
  for i := 0 to ScMarkerCount - 1 do
  begin
    case i of
      0: Marker := 'Data.p4k';
      1: Marker := 'build_manifest.id';
      2: Marker := 'Bin64';
      3: Marker := 'StarCitizen_Launcher.exe';
      4: Marker := 'EasyAntiCheat';
      5: Marker := 'client.crt';
      6: Marker := 'USER';
      7: Marker := 'ScreenShots';
      8: Marker := 'logbackups';
      9: Marker := 'Game.log';
    else
      { Fails safe if ScMarkerCount ever runs past this list: Dir + '\'
        always exists, so the folder is refused rather than wiped. }
      Marker := '';
    end;
    if FileExists(Dir + '\' + Marker) or DirExists(Dir + '\' + Marker) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function LooksLikeScInstall(const Dir: String): Boolean;
var
  i: Integer;
begin
  { Judged by game files, not the registry, so it still works when every
    recorded path is stale. Covers the folder itself and each channel folder
    under it. }
  Result := HasScGameData(Dir);
  for i := 0 to ScChannelCount - 1 do
    if not Result then
      Result := HasScGameData(Dir + '\' + ScChannelName(i));
end;

function RegisteredScPathUnder(const Root: String): String;
var
  Nodes: array[0..1] of String;
  Names: array[0..2] of String;
  Value: String;
  n, v: Integer;
begin
  { Every place the installer or the app records the SC install, in both
    registry nodes, and ALL of them count (sc_directory is only written by the
    installer and goes stale; sc_install_root is what the app maintains). }
  Result := '';
  Nodes[0] := SCRegNode;
  Nodes[1] := SCLegacyRegNode;
  Names[0] := 'sc_install_root';
  Names[1] := 'game_install_path';
  Names[2] := 'sc_directory';
  for n := 0 to 1 do
    for v := 0 to 2 do
    begin
      Value := '';
      if (Result = '') and RegQueryStringValue(HKCU, Nodes[n], Names[v], Value)
         and IsAbsoluteDir(Value) and PathUnderRoot(CanonDir(Value), Root) then
        Result := Value;
    end;
end;

function UnsafeDeleteRootReason(const RawRoot: String): String;
var
  Root, Hit, T: String;
begin
  { A data or cache folder override can be any folder the user picked. Returns
    why deleting inside it is unsafe, as the end of a sentence the user reads
    ("... not cleaned because it is a whole drive"), or '' when it is fine. }
  Result := '';
  Root := Trim(RawRoot);
  if Root = '' then
  begin
    Result := 'the folder setting is empty';
    Exit;
  end;
  if (Length(Root) = 2) and (Copy(Root, 2, 1) = ':') then
  begin
    Result := 'it is a whole drive';
    Exit;
  end;
  if not IsAbsoluteDir(Root) then
  begin
    Result := 'it is not a full folder path';
    Exit;
  end;
  T := Root;
  StringChangeEx(T, '/', '\', True);
  if (Copy(T, 1, 4) = '\\?\') or (Copy(T, 1, 4) = '\\.\') then
  begin
    Result := 'it is a special device path';
    Exit;
  end;
  Root := CanonDir(Root);
  if (Length(Root) = 2) and (Copy(Root, 2, 1) = ':') then
  begin
    Result := 'it is a whole drive';
    Exit;
  end;
  { Checked again after canonicalising: a value such as \\ or // comes out
    empty, and an empty root would make every path below start at the root of
    the current drive. }
  if not IsAbsoluteDir(Root) then
  begin
    Result := 'it is not a full folder path';
    Exit;
  end;
  if Copy(Root, 1, 2) = '\\' then
  begin
    T := Copy(Root, 3, Length(Root));
    if Pos('\', T) > 0 then
      T := Copy(T, Pos('\', T) + 1, Length(T))
    else
      T := '';
    if (Copy(T, 2, 1) = '$') and ((Length(T) = 2) or (Copy(T, 3, 1) = '\')) then
    begin
      Result := 'it is a whole drive shared over the network';
      Exit;
    end;
    if Pos('\', T) = 0 then
    begin
      Result := 'it is the top of a network share';
      Exit;
    end;
  end;
  { The local %USERPROFILE%\Documents stays a real folder when OneDrive or the
    Location tab moves the shell's Documents, and the data page even suggests
    a path inside it (SuggestLocalDataDir). }
  if SameDir(Root, GetDocumentsBase()) or SameDir(Root, ExpandConstant('{userdocs}')) or
     SameDir(Root, ExpandConstant('{%USERPROFILE}\Documents')) then
  begin
    Result := 'it is the Documents folder';
    Exit;
  end;
  if SameDir(Root, ExpandConstant('{%USERPROFILE}')) then
  begin
    Result := 'it is your user profile folder';
    Exit;
  end;
  if SameDir(Root, ExpandConstant('{app}')) then
  begin
    Result := 'it is the folder Smart Citizen is installed in';
    Exit;
  end;
  if IsLinkDir(Root) then
  begin
    Result := 'it is a junction or symbolic link';
    Exit;
  end;
  Hit := RegisteredScPathUnder(Root);
  if Hit <> '' then
  begin
    if SameDir(Hit, Root) then
      Result := 'it is the Star Citizen install folder'
    else
      Result := 'it contains the Star Citizen install (' + Hit + ')';
    Exit;
  end;
  if LooksLikeScInstall(Root) then
    Result := 'it holds Star Citizen game files';
end;

procedure RemoveEmptyIfSafe(const Dir: String);
begin
  if (Dir <> '') and (UnsafeDeleteRootReason(Dir) = '') and DirExists(CanonDir(Dir)) then
  begin
    if RemoveDir(CanonDir(Dir)) then
      Log('Removed now-empty folder: ' + CanonDir(Dir))
    else
      Log('Folder left in place (not empty, or in use): ' + CanonDir(Dir));
  end;
end;

function DeleteOwnedItem(const Path: String; const IsDir: Boolean): String;
begin
  { Deletes one app-owned folder and everything in it (IsDir), or one file.
    Path must be canonical and must not hold a wildcard: Windows matches
    wildcards against 8.3 short names too. Returns a line for the summary when
    something was left behind, '' otherwise. }
  Result := '';
  Log('Deleting owned item: ' + Path);
  if not DelTree(LongPath(Path), IsDir, True, IsDir) then
    Result := '  ' + Path + ': could not delete all of it' + #13#10;
end;

function DeleteAppLogs(const LogsDir: String): String;
var
  FR: TFindRec;
  Names: TStringList;
  Name: String;
  i: Integer;
  Failed: Boolean;
begin
  { logs may be a folder the user already had, so only the app's own files go:
    crash_*.log (crash_handler.py) and smart_citizen_*.log (the Log tab's
    export), judged by their long names, then the folder if that emptied it. }
  Result := '';
  if IsLinkDir(LogsDir) then
  begin
    Log('Refusing to clean logs through a link: ' + LogsDir);
    Result := '  ' + LogsDir + ': not cleaned because it is a junction or symbolic link' + #13#10;
    Exit;
  end;
  Names := TStringList.Create;
  try
    if FindFirst(LongPath(LogsDir) + '\*', FR) then
    try
      repeat
        Name := FR.Name;
        if ((FR.Attributes and $10) = 0) and
           ((CompareText(Copy(Name, 1, 6), 'crash_') = 0) or
            (CompareText(Copy(Name, 1, 14), 'smart_citizen_') = 0)) and
           (Length(Name) > 4) and
           (CompareText(Copy(Name, Length(Name) - 3, 4), '.log') = 0) then
          Names.Add(Name);
      until not FindNext(FR);
    finally
      FindClose(FR);
    end;
    Failed := False;
    for i := 0 to Names.Count - 1 do
      if DeleteOwnedItem(LogsDir + '\' + Names[i], False) <> '' then
        Failed := True;
  finally
    Names.Free;
  end;
  if Failed then
    Result := '  ' + LogsDir + ': could not delete all of Smart Citizen''s log files' + #13#10;
  RemoveEmptyIfSafe(LogsDir);
end;

function DeleteOwnedSubpaths(const RawRoot: String; const IsCacheRoot: Boolean): String;
var
  Root, Reason, Item: String;
  i: Integer;
begin
  { Deletes only what the app writes under Root and never Root itself:
      data folder:  the channel folders, Smart Citizen's own files in logs,
                    the old root-level user.ini / overrides.ini / base.ini,
                    and the pre-0.9.3 flat cache, but only when it holds a
                    Smart Citizen cache (LooksLikeScCache). Another program's
                    folder named "cache" stays, and so does Root. A normal
                    uninstall clears the flat cache under the same rule.
      cache folder: the channel folders (each holds cache\dataforge)
    Root is removed afterwards only if that left it empty. Returns a line for
    every folder it refused or could not clear, '' when all went well. }
  Result := '';
  Reason := UnsafeDeleteRootReason(RawRoot);
  if Reason <> '' then
  begin
    Log('Refusing to delete under ' + RawRoot + ' (' + Reason + ').');
    Result := '  ' + RawRoot + ': not cleaned because ' + Reason + #13#10;
    Exit;
  end;
  Root := CanonDir(RawRoot);

  for i := 0 to ScChannelCount - 1 do
  begin
    Item := Root + '\' + ScChannelName(i);
    if DirExists(Item) then
      Result := Result + DeleteOwnedItem(Item, True);
  end;

  if not IsCacheRoot then
  begin
    Item := Root + '\logs';
    if DirExists(Item) then
      Result := Result + DeleteAppLogs(Item);
    Item := Root + '\cache';
    if DirExists(Item) then
    begin
      if LooksLikeScCache(Item) then
        Result := Result + DeleteOwnedItem(Item, True)
      else
        Log('Leaving ' + Item + ' alone: it holds no Smart Citizen cache (no base.ini, dataforge folder or channel cache).');
    end;
    for i := 0 to 2 do
    begin
      case i of
        0: Item := Root + '\user.ini';
        1: Item := Root + '\overrides.ini';
      else
        Item := Root + '\base.ini';
      end;
      if FileExists(Item) then
        Result := Result + DeleteOwnedItem(Item, False);
    end;
  end;

  RemoveEmptyIfSafe(Root);
end;

function IsScChannelName(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 0 to ScChannelCount - 1 do
    if CompareText(Name, ScChannelName(i)) = 0 then
      Result := True;
end;

function DeleteQueuedOldCache(const RawLeaf: String): String;
var
  Leaf, CacheDir, ChannelDir, Base, Reason: String;
begin
  { After a cache move the app queues the old DataForge tree,
    <base>\<channel>\cache\dataforge, for deletion after the next re-extract
    (pending_cache_cleanup). The wipe deletes the registry value that remembers
    it, so it deletes the tree now: that exact shape only, and only when <base>
    passes the same safety checks as any other root. }
  Result := '';
  if not IsAbsoluteDir(RawLeaf) then
    Exit;
  Leaf := CanonDir(RawLeaf);
  CacheDir := ExtractFileDir(Leaf);
  ChannelDir := ExtractFileDir(CacheDir);
  Base := ExtractFileDir(ChannelDir);
  if (CompareText(ExtractFileName(Leaf), 'dataforge') <> 0) or
     (CompareText(ExtractFileName(CacheDir), 'cache') <> 0) or
     not IsScChannelName(ExtractFileName(ChannelDir)) or not DirExists(Leaf) then
    Exit;
  Reason := UnsafeDeleteRootReason(Base);
  if Reason <> '' then
  begin
    Log('Refusing to delete queued old cache ' + Leaf + ' (' + Reason + ').');
    Result := '  ' + Base + ': not cleaned because ' + Reason +
              ', so the old DataForge cache in it was left' + #13#10;
    Exit;
  end;
  Result := DeleteOwnedItem(Leaf, True);
  RemoveEmptyIfSafe(CacheDir);
  RemoveEmptyIfSafe(ChannelDir);
  RemoveEmptyIfSafe(Base);
end;

procedure DeleteAllUserSettings();
var
  UserDataDir, CacheDir, DefaultDataDir, DefaultCacheDir, QueuedOldCache: String;
  LegacyDir, Notes, Advice: String;
begin
  { The one deliberate exception to the #172 persistence lock, reached only from
    the opt-in checkbox. Everything is resolved BEFORE the registry node goes,
    because the user_data_dir / cache_dir overrides and the queued old cache
    live in it. The default folders are cleaned too when an override points
    elsewhere: they are named for the app, and an old copy may still be there. }
  Log('User opted in to full settings wipe (issue #357).');
  UserDataDir := GetDocumentsDir();
  CacheDir := GetCacheDir();
  DefaultDataDir := GetDefaultDocumentsDir();
  DefaultCacheDir := GetLocalCacheDefault();
  if not RegQueryStringValue(HKCU, SCRegNode, 'pending_cache_cleanup', QueuedOldCache) then
    QueuedOldCache := '';

  Notes := DeleteOwnedSubpaths(UserDataDir, False);
  if not SameDir(DefaultDataDir, UserDataDir) and DirExists(DefaultDataDir) then
    Notes := Notes + DeleteOwnedSubpaths(DefaultDataDir, False);

  { Named for the old app, so it is safe to delete whole. }
  LegacyDir := CanonDir(GetLegacyDocumentsDir());
  if DirExists(LegacyDir) then
    Notes := Notes + DeleteOwnedItem(LegacyDir, True);

  if not SameDir(CacheDir, UserDataDir) then
    Notes := Notes + DeleteOwnedSubpaths(CacheDir, True);
  if not SameDir(DefaultCacheDir, CacheDir) and not SameDir(DefaultCacheDir, UserDataDir)
     and DirExists(DefaultCacheDir) then
    Notes := Notes + DeleteOwnedSubpaths(DefaultCacheDir, True);
  Notes := Notes + DeleteQueuedOldCache(QueuedOldCache);
  { A cache folder nested in the data folder only empties it after this pass. }
  RemoveEmptyIfSafe(UserDataDir);

  if RegDeleteKeyIncludingSubkeys(HKCU, SCRegNode) then
    Log('Deleted HKCU registry node: ' + SCRegNode)
  else
    Log('HKCU registry node delete returned false (may already be absent).');
  RegDeleteKeyIncludingSubkeys(HKCU, SCLegacyRegNode);

  if Notes <> '' then
  begin
    Advice := '';
    if Pos(': not cleaned because ', Notes) > 0 then
      Advice := Advice + 'Smart Citizen did not clean a folder marked "not cleaned", so ' +
                'its own files there are still in place. Folders named for Smart Citizen ' +
                'inside it, such as Documents\Smart Citizen, may still have been cleaned. ';
    if Pos(': could not delete', Notes) > 0 then
      Advice := Advice + 'Anything that could not be deleted may be open in another ' +
                'program. Close it and delete what is left yourself if you want it gone.';
    MsgBox('Smart Citizen did not remove everything:' + #13#10 + #13#10 + Notes + #13#10 +
           Trim(Advice), mbInformation, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if DeleteAllSettingsChecked then
    begin
      { #357: explicit opt-in on the uninstall dialog. It replaces the
        cache-only cleanup below and deletes everything that cleanup would,
        except in a folder it refuses (folders named for the app inside one are
        still cleaned). }
      DeleteAllUserSettings();
    end
    else
    begin
      { Same cleanup contract as install/upgrade: per-channel \cache gets
        nuked, \backups + user.ini survive so a reinstall picks up where
        the user left off. Only \cache is disposable, and a data folder that is
        not safe to delete in is left alone (see CleanCachedData).

        Persistence lock (#172): do NOT delete the live registry node
        'Software\Osiris DevWorks\Smart Citizen' or any of its values here —
        user_data_dir (and the other settings) MUST survive uninstall so the
        next install pre-fills the user's chosen data folder. Wiping the node
        is exactly the regression that let the data-folder choice revert.
        (Exception: the #357 opt-in branch above.) }
      Log('Cleaning cached data during uninstall');
      CleanCachedData();
    end;
  end;
end;

procedure DeleteAllCheckBoxOnClick(Sender: TObject);
var
  CB: TNewCheckBox;
  Response: Integer;
begin
  { The warning is a popup when the box is ticked, not text on the dialog:
    TNewCheckBox does not word-wrap its caption, so a long inline warning runs
    off the form. Declining unticks the box again. }
  CB := TNewCheckBox(Sender);
  if not CB.Checked then
    Exit;

  Response := MsgBox(
    'This will permanently delete:' + #13#10 +
    '  - Your Smart Citizen settings (registry), including your owned blueprints list' + #13#10 +
    '  - The Smart Citizen files in your user data folder (custom edits, backups, logs)' + #13#10 +
    '  - The cached DataForge data' + #13#10 + #13#10 +
    'This cannot be undone. Click OK to confirm, or Cancel to keep your settings.',
    mbError, MB_OKCANCEL);
  if Response <> IDOK then
    CB.Checked := False;
end;

function InitializeUninstall(): Boolean;
var
  ConfirmForm: TSetupForm;
  MsgLabel: TNewStaticText;
  DeleteCheckBox: TNewCheckBox;
  UninstallButton, CancelButton: TNewButton;
begin
  Result := True;
  DeleteAllSettingsChecked := False;

  { A silent uninstall must never wait on a dialog: /SILENT is the quiet string
    Inno registers (winget, Intune), /VERYSILENT is the auto-updater's cleanup.
    The one silent run with a person present is the "uninstall old version only"
    branch of InitializeSetup, which passes /SHOWDELETEOPTION=1 to opt back in. }
  if UninstallSilent() and (ExpandConstant('{param:SHOWDELETEOPTION|0}') <> '1') then
    Exit;

  { The last two arguments are KeepSizeX=False, KeepSizeY=True. }
  ConfirmForm := CreateCustomForm(ScaleX(420), ScaleY(150), False, True);
  try
    ConfirmForm.Caption := 'Uninstall Smart Citizen';

    MsgLabel := TNewStaticText.Create(ConfirmForm);
    MsgLabel.Parent := ConfirmForm;
    MsgLabel.Left := ScaleX(16);
    MsgLabel.Top := ScaleY(16);
    MsgLabel.Width := ConfirmForm.ClientWidth - ScaleX(32);
    MsgLabel.AutoSize := False;
    MsgLabel.WordWrap := True;
    MsgLabel.Height := ScaleY(32);
    { A statement, not a question: Inno's own "Are you sure..." follows. }
    MsgLabel.Caption := 'You are about to uninstall Smart Citizen.';

    { One short line on purpose: a TNewCheckBox clips a long caption. }
    DeleteCheckBox := TNewCheckBox.Create(ConfirmForm);
    DeleteCheckBox.Parent := ConfirmForm;
    DeleteCheckBox.Left := ScaleX(16);
    DeleteCheckBox.Top := MsgLabel.Top + MsgLabel.Height + ScaleY(12);
    DeleteCheckBox.Width := ConfirmForm.ClientWidth - ScaleX(32);
    DeleteCheckBox.Height := ScaleY(17);
    DeleteCheckBox.Caption := 'Also delete all saved settings';
    DeleteCheckBox.Checked := False;
    DeleteCheckBox.OnClick := @DeleteAllCheckBoxOnClick;

    UninstallButton := TNewButton.Create(ConfirmForm);
    UninstallButton.Parent := ConfirmForm;
    UninstallButton.Width := ScaleX(90);
    UninstallButton.Height := ScaleY(23);
    UninstallButton.Top := ConfirmForm.ClientHeight - ScaleY(16) - UninstallButton.Height;
    UninstallButton.Left := ConfirmForm.ClientWidth - ScaleX(16) - UninstallButton.Width;
    UninstallButton.Caption := 'Uninstall';
    UninstallButton.ModalResult := mrOk;
    UninstallButton.Default := True;

    CancelButton := TNewButton.Create(ConfirmForm);
    CancelButton.Parent := ConfirmForm;
    CancelButton.Width := ScaleX(90);
    CancelButton.Height := ScaleY(23);
    CancelButton.Top := UninstallButton.Top;
    CancelButton.Left := UninstallButton.Left - ScaleX(8) - CancelButton.Width;
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;

    if ConfirmForm.ShowModal() = mrOk then
    begin
      { A ticked box has already been through the warning popup. }
      DeleteAllSettingsChecked := DeleteCheckBox.Checked;
      Result := True;
    end
    else
      Result := False;
  finally
    ConfirmForm.Free;
  end;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  UninstallString: String;
  UninstallExe: String;
  ButtonPressed: Integer;
begin
  Result := True;

  { Check if the application is already installed }
  UninstallString := GetUninstallString();
  if UninstallString <> '' then
  begin
    { Zombie-entry guard: if the uninstall string points at a file that's
      no longer on disk, the prior "upgrade?" dialog would offer choices
      that would all fail (Exec against a missing unins000.exe is a silent
      no-op, leaving the dangling registry entry in place forever). Clear
      the stale entry and continue as a fresh install — skipping the
      dialog entirely since there's nothing real to upgrade from. }
    UninstallExe := RemoveQuotes(UninstallString);
    if not FileExists(UninstallExe) then
    begin
      ClearStaleUninstallEntry();
      Exit;  { Result is already True — proceed with fresh install }
    end;

    { Show custom dialog with three options. SuppressibleMsgBox, not MsgBox:
      the in-app auto-updater (#211) runs this installer with
      /SILENT /SUPPRESSMSGBOXES /AUTOUPDATE=1 (_launch_installer_and_quit in
      src/gui/main_window.py), and /SUPPRESSMSGBOXES only answers
      SuppressibleMsgBox calls. As a plain MsgBox this stopped every
      auto-update on the question, and a click on NO uninstalled the app
      instead of updating it. Suppressed, it returns IDYES (upgrade in
      place). Interactive and plain /SILENT runs still show the box. }
    ButtonPressed := SuppressibleMsgBox('A previous version of this application is already installed.' + #13#10 + #13#10 +
                            'Choose an option:' + #13#10 +
                            '  - Click YES to uninstall the old version and install this new version' + #13#10 +
                            '  - Click NO to uninstall the old version only (without installing)' + #13#10 +
                            '  - Click CANCEL to exit without making any changes',
                            mbConfirmation, MB_YESNOCANCEL, IDYES);

    case ButtonPressed of
      IDYES: begin
        { Continue with upgrade (uninstall old, then install new) }
        Result := True;
      end;
      IDNO: begin
        { Uninstall only, without installing new version }
        UninstallString := RemoveQuotes(UninstallString);
        { A person is present, so let the uninstaller show its delete option. }
        Exec(UninstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES /SHOWDELETEOPTION=1','', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Result := False;
      end;
      IDCANCEL: begin
        { Cancel installation }
        Result := False;
      end;
    end;
  end;
end;

function IsValidSCRoot(const Path: String): Boolean;
var
  BasePath: String;
begin
  { Returns True if Path is an SC install root: it contains at least one
    channel subdirectory (LIVE, PTU, etc.). Mirrors the app's
    _is_valid_sc_root(). Guards against stale registry values like
    'SmartCitizen 1.4.1'. }
  BasePath := RemoveBackslash(Path) + '\';
  Result := DirExists(BasePath + 'LIVE') or DirExists(BasePath + 'PTU') or
            DirExists(BasePath + 'EPTU') or DirExists(BasePath + 'HOTFIX') or
            DirExists(BasePath + 'TECH-PREVIEW');
end;

function IsValidSCPath(const Path: String): Boolean;
var
  ChannelDir: String;
  LastName: String;
begin
  { Returns True if Path looks like a valid Star Citizen install path.
    Accepts either:
      - a root containing channel subdirectories (IsValidSCRoot), or
      - an existing channel folder (last component is a channel name like
        LIVE). It must exist, so a path left behind by a moved or removed
        install falls through to auto-detect instead of being pre-filled.
    The last component is read with the trailing backslash removed, since
    ExtractFileName of a path ending in '\' is always ''. }
  ChannelDir := RemoveBackslash(Path);
  LastName := LowerCase(ExtractFileName(ChannelDir));
  Result := (((LastName = 'live') or (LastName = 'ptu') or (LastName = 'eptu') or
              (LastName = 'hotfix') or (LastName = 'tech-preview')) and
             DirExists(ChannelDir)) or
            IsValidSCRoot(Path);
end;

procedure InitializeWizard();
var
  NewRegPath: String;
  LegacyRegPath: String;
  DefaultPath: String;
  SavedPath: String;
  SCRoot: String;
  ActiveChannel: String;
  DefaultLeaf: String;
  SavedDataDir: String;
  SavedLanguage: String;
  LanguageIndex: Integer;
begin
  { App UI/string language — first page, anchored to wpWelcome. Kept ahead
    of every other custom page (and the built-in Select Destination /
    Program Group / Tasks pages) so it's the first choice a user makes. }
  LanguageChoicePage := CreateInputOptionPage(
    wpWelcome,
    'Select Language',
    'Choose the language Smart Citizen starts in.',
    'This sets both the app''s interface language and, where available, '
    + 'the in-game localization strings it loads.'
    + #13#10 + #13#10 +
    'You can change this anytime from the app''s Config tab.',
    True,
    False
  );
  { Plain ASCII labels, matching the app's own Config-tab language combo
    (ConfigTab._populate_language_combo does lang.replace('_', ' ').title(),
    not native-script names) — installer.iss has no UTF-8 BOM, so accented
    characters risk mangling under ISCC's ANSI-codepage fallback. }
  LanguageChoicePage.Add('English');
  LanguageChoicePage.Add('French');
  LanguageChoicePage.Add('Portuguese (Brazil)');
  LanguageChoicePage.Add('Spanish');
  LanguageChoicePage.Add('Japanese');
  LanguageChoicePage.Add('Chinese');
  LanguageChoicePage.Add('Italian');
  LanguageChoicePage.Add('German');
  LanguageChoicePage.Add('Turkish');
  LanguageChoicePage.Add('Korean');
  LanguageChoicePage.Add('Traditional Chinese');

  { Pre-select the prior choice on a reinstall so an upgrade doesn't
    silently reset a non-English user back to English. Defaults to
    English (index 0) when nothing is saved yet or the saved value
    doesn't match a known option. }
  LanguageIndex := 0;
  LanguageChoiceUnknownSaved := False;
  if RegQueryStringValue(HKCU, SCRegNode,
       'selected_language', SavedLanguage) then
  begin
    if CompareText(SavedLanguage, 'french') = 0 then
      LanguageIndex := 1
    else if CompareText(SavedLanguage, 'portuguese_br') = 0 then
      LanguageIndex := 2
    else if CompareText(SavedLanguage, 'spanish') = 0 then
      LanguageIndex := 3
    else if CompareText(SavedLanguage, 'japanese') = 0 then
      LanguageIndex := 4
    else if CompareText(SavedLanguage, 'chinese') = 0 then
      LanguageIndex := 5
    else if CompareText(SavedLanguage, 'italian') = 0 then
      LanguageIndex := 6
    else if CompareText(SavedLanguage, 'german') = 0 then
      LanguageIndex := 7
    else if CompareText(SavedLanguage, 'turkish') = 0 then
      LanguageIndex := 8
    else if CompareText(SavedLanguage, 'korean') = 0 then
      LanguageIndex := 9
    else if CompareText(SavedLanguage, 'chinese_traditional') = 0 then
      LanguageIndex := 10
    else if CompareText(SavedLanguage, 'english') <> 0 then
      { A saved value that matches none of this page's options — e.g. a
        newer app version shipped a 5th language before this installer's
        option list caught up. Flag it so the write-back below leaves the
        real saved value alone instead of clobbering it with 'english'. }
      LanguageChoiceUnknownSaved := True;
  end;
  LanguageChoicePage.SelectedValueIndex := LanguageIndex;

  { Registry path resolution order:
      1. NEW "Smart Citizen" node (post-0.9.2 rebrand) — every app launch
         writes here, and the one-shot migrate_registry_appname() in the
         app's main() deletes the legacy subtree after copying values over.
         That means any sc_directory we wrote to the legacy node on a
         previous installer run was subsequently wiped by the app. Writing
         and reading from the NEW node is the fix.
      2. LEGACY "SC Localization Editor" node — kept as a read-side
         fallback so users who upgrade from a version earlier than 0.9.2
         (and therefore have no NEW node yet) still get their path
         prefilled on the first reinstall. The installer's
         WriteInstallerChoicesToRegistry (called from CurStepChanged
         at ssPostInstall) writes to the NEW node regardless, so
         subsequent reinstalls resolve via path 1. }
  NewRegPath := SCRegNode;
  LegacyRegPath := SCLegacyRegNode;
  DefaultPath := '';

  { 0.9.3+: the app stores the SC install root (parent of LIVE/PTU/...) in
    sc_install_root. Always default the installer's prompt to the LIVE
    subfolder — the page title says "Star Citizen LIVE Directory" and
    users consistently expect LIVE to be offered regardless of which
    channel the app is currently pointed at. The active_channel value is
    ignored here on purpose; the app-side channel switcher handles
    per-channel paths at runtime. The value must be a root, not a channel
    path, or the LIVE suffix below would double up (...\LIVE\LIVE). }
  if RegQueryStringValue(HKCU, NewRegPath, 'sc_install_root', SCRoot) and (SCRoot <> '') and IsValidSCRoot(SCRoot) then
  begin
    ActiveChannel := 'LIVE';
    DefaultPath := AddBackslash(SCRoot) + ActiveChannel;
  end;

  { Fall back to previously saved sc_directory / game_install_path in the
    NEW node, then the LEGACY node.  Each value is validated to ensure it
    actually looks like a valid SC install path (either an existing channel
    folder, or contains channel subdirectories).  Validation is folded into
    the condition so a stale value causes fallthrough to the next option. }
  if DefaultPath = '' then
  begin
    if RegQueryStringValue(HKCU, NewRegPath, 'sc_directory', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, NewRegPath, 'game_install_path', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, LegacyRegPath, 'sc_directory', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if RegQueryStringValue(HKCU, LegacyRegPath, 'game_install_path', SavedPath) and (SavedPath <> '') and IsValidSCPath(SavedPath) then
      DefaultPath := SavedPath
    else if DirExists('C:\Program Files\Roberts Space Industries\StarCitizen\LIVE') then
      DefaultPath := 'C:\Program Files\Roberts Space Industries\StarCitizen\LIVE'
    else if DirExists('C:\Program Files (x86)\Roberts Space Industries\StarCitizen\LIVE') then
      DefaultPath := 'C:\Program Files (x86)\Roberts Space Industries\StarCitizen\LIVE'
    else
      DefaultPath := 'C:\Program Files\Roberts Space Industries\StarCitizen';
  end;

  { Normalize the prompt default to the LIVE subfolder: if the resolved
    path ends in a non-LIVE channel name (because the app persisted
    game_install_path as the channel-suffixed path while the friend was
    on a non-LIVE channel), swap the suffix for \LIVE. The page is
    specifically asking for the LIVE directory; offering a non-LIVE one
    as the default confuses users whose main SC install is LIVE. A saved
    value may end in a backslash, which would hide its last component from
    ExtractFileName, so drop it first (a drive root like D:\ keeps it). }
  DefaultPath := RemoveBackslashUnlessRoot(DefaultPath);
  DefaultLeaf := LowerCase(ExtractFileName(DefaultPath));
  if (DefaultLeaf = 'ptu') or (DefaultLeaf = 'eptu') or (DefaultLeaf = 'hotfix') or
     (DefaultLeaf = 'tech-preview') then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE';

  SCDirectoryPage := CreateInputDirPage(
    wpSelectTasks,
    ExpandConstant('{cm:SCDirectoryPrompt}'),
    ExpandConstant('{cm:SCDirectoryPromptDesc}'),
    ExpandConstant('{cm:SCDirectoryDefaultDesc}' + #13#10 + '{cm:SCDirectoryDefaultPath}'),
    False,
    'Star Citizen LIVE Directory'
  );

  SCDirectoryPage.Add('');
  SCDirectoryPage.Values[0] := DefaultPath;

  { Rebrand: if the prior install is still under the old "SC Localization
    Editor" folder name, override the prefilled app dir (and start-menu
    group) to the new brand. Any other prior location — including one the
    user customized — is preserved. }
  if Pos('SC Localization Editor', WizardForm.DirEdit.Text) > 0 then
    WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Osiris DevWorks\Smart Citizen');
  if Pos('SC Localization Editor', WizardForm.GroupEdit.Text) > 0 then
    WizardForm.GroupEdit.Text := 'Smart Citizen';

  { Smart Citizen data location: always exposed so users can move the
    cache, custom edits, and backups off the default Documents folder —
    useful even when Documents isn't OneDrive-synced (e.g. user wants the
    2 GB cache on a faster SSD or a different drive). The default value
    adapts:
      1. If a prior override exists, pre-fill it (respects the user's
         previous choice across reinstalls).
      2. Else if Documents is OneDrive-synced and has no Smart Citizen
         folder yet, suggest the local %USERPROFILE%\Documents\Smart Citizen
         junction (escapes the sync).
      3. Else pre-fill Documents\Smart Citizen (the natural default).
    WriteInstallerChoicesToRegistry compares the final value against the
    natural default and only writes user_data_dir when the user actually
    picked something different — so leaving the field at its default
    keeps the registry clean and lets the app's dynamic Documents
    resolution win. }
  DataDirPage := CreateInputDirPage(
    SCDirectoryPage.ID,
    'Smart Citizen Data Location',
    'Choose where Smart Citizen stores user.ini, source cache, enhancement INIs, and backups.',
    'Smart Citizen stores your custom edits (user.ini), the localization source cache, '
    + 'generated enhancement INIs, and rolling backups under this folder. The default is your '
    + 'Documents folder.'
    + #13#10 + #13#10 +
    'The ~1.4 GB DataForge XML cache lives on its own page next — splitting them lets you keep '
    + 'your tiny user data wherever you like while sending the cache to a fast SSD.'
    + #13#10 + #13#10 +
    'Consider a custom location if:'
    + #13#10 +
    '  - Your Documents folder is synced to OneDrive (causes occasional "Access is denied"'
    + #13#10 +
    '    errors and slow cleanup of generated INIs)'
    + #13#10 +
    '  - You manage multiple profiles or installs and want them isolated'
    + #13#10 + #13#10 +
    'You can change this later from the app''s Config tab.',
    False,
    'Smart Citizen Data'
  );
  DataDirPage.Add('');

  { Pre-fill: existing override > OneDrive suggestion > Documents default.
    A stale value (missing folder or versioned leftover) falls through to
    the default rather than prefilling a bad path. Issue #120.
    The OneDrive suggestion is for a NEW data folder only. With no override,
    an existing Documents\Smart Citizen is where the app already keeps its
    data, and moving off it would leave user.ini behind. A silent update
    (the in-app updater) never shows this page, so nobody could stop that.
    The app's own startup warning offers the one-click move, which migrates
    the data. }
  if RegQueryStringValue(HKCU, NewRegPath, 'user_data_dir', SavedDataDir) and
     (SavedDataDir <> '') and not IsStalePrefill(SavedDataDir) then
    DataDirPage.Values[0] := SavedDataDir
  else if IsDocsOnOneDrive() and
          not DirExists(GetDocumentsBase() + '\Smart Citizen') then
    DataDirPage.Values[0] := SuggestLocalDataDir()
  else
    DataDirPage.Values[0] := GetDefaultDocumentsDir();

  { 1.4.1+: DataForge cache lives on its own page so users can split it
    off the user-data folder. The app's runtime default is
    %LOCALAPPDATA%\Smart Citizen (never OneDrive-synced) and that's what
    we offer here. WriteInstallerChoicesToRegistry only writes cache_dir
    when the field differs from this default, so users who accept the
    default keep the registry clean and let the app's resolver win. }
  CacheDirPage := CreateInputDirPage(
    DataDirPage.ID,
    'DataForge Cache Location',
    'Choose where Smart Citizen stores the ~1.4 GB DataForge XML cache.',
    'The DataForge cache contains ~28,000 entity XMLs extracted from Star Citizen''s '
    + 'Data.p4k file. It''s used to generate the in-game item descriptions you see in the '
    + 'Enhancements tab.'
    + #13#10 + #13#10 +
    'The default keeps the cache in your Windows AppData\Local folder — never synced to '
    + 'OneDrive — so extraction and cleanup stay fast even when your Documents are.'
    + #13#10 + #13#10 +
    'Pick a custom location if you want to:'
    + #13#10 +
    '  - Move the 1.4 GB tree to a different drive (faster SSD, or to free C: space)'
    + #13#10 +
    '  - Share the cache between multiple Smart Citizen installs on this PC'
    + #13#10 + #13#10 +
    'You can change this later from the app''s Config tab. Changing the path triggers a '
    + 'one-time re-extraction.',
    False,
    'DataForge Cache'
  );
  CacheDirPage.Add('');

  { Pre-fill: existing override > LOCALAPPDATA default. No OneDrive
    branch because LOCALAPPDATA is the OneDrive-safe location by
    definition (it's machine-local, never roamed). }
  if RegQueryStringValue(HKCU, NewRegPath, 'cache_dir', SavedDataDir) and
     (SavedDataDir <> '') and not IsStalePrefill(SavedDataDir) then
    CacheDirPage.Values[0] := SavedDataDir
  else
    CacheDirPage.Values[0] := GetLocalCacheDefault();

  { #180: Start mode. Simple is a near-empty one-button screen for new users;
    Advanced is the full interface. Radio buttons (Exclusive=True). Default to
    Simple, but pre-select the user's prior choice on a reinstall so an upgrade
    doesn't silently flip an Advanced user back to Simple. }
  ModeChoicePage := CreateInputOptionPage(
    CacheDirPage.ID,
    'Start Mode',
    'Choose how Smart Citizen opens.',
    'Simple mode provides a single button that generates Smart Citizen '
    + 'enhancements with default settings — ideal if you just want enhanced '
    + 'strings fast. Advanced mode shows the full interface with every tab and '
    + 'option.'
    + #13#10 + #13#10 +
    'You can switch modes anytime from inside the app.',
    True,
    False
  );
  ModeChoicePage.Add('Simple mode (recommended)');
  ModeChoicePage.Add('Advanced mode');
  if RegQueryStringValue(HKCU, NewRegPath, 'ui_mode', SavedDataDir) and
     (CompareText(SavedDataDir, 'advanced') = 0) then
    ModeChoicePage.SelectedValueIndex := 1
  else
    ModeChoicePage.SelectedValueIndex := 0;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Chosen: String;
  Suggested: String;
  Response: Integer;
begin
  { Active OneDrive warning (#172). The data-folder page's pre-fill only
    *steers* the default away from a OneDrive-redirected Documents; it does
    nothing about a user who browses to a OneDrive folder by hand, or a
    pre-filled OneDrive override carried over from a prior install. Validate
    the ENTERED path at Next-click against any OneDrive root (not just the
    shell Documents folder) and make the user acknowledge it. This is the
    installer-side mirror of the app's startup / Config-tab warning (#174),
    and the "switch to a local folder" path matches #174's
    "Move to a Local Folder" so both surfaces behave identically. }
  Result := True;
  if (DataDirPage = nil) or (CurPageID <> DataDirPage.ID) then
    Exit;

  { Silent installs, including the in-app auto-updater's /SILENT run (#211),
    never show this page, but Setup still "clicks" Next through it, so this
    function runs. The box below is a plain MsgBox, so /SUPPRESSMSGBOXES
    does not answer it and the run stops on the question. Its YES branch
    returns False, and a silent Setup that gets False here exits without
    installing. So keep the folder as it is (the NO answer). After the
    relaunch the app shows its own OneDrive warning (#174,
    _maybe_warn_onedrive_data_dir in src/gui/main_window.py). }
  if WizardSilent() then
    Exit;

  Chosen := Trim(DataDirPage.Values[0]);
  if not IsPathOnOneDrive(Chosen) then
    Exit;

  Suggested := SuggestLocalDataDir();
  Response := MsgBox(
    'The data folder you chose is inside OneDrive:' + #13#10 + #13#10 +
    '  ' + Chosen + #13#10 + #13#10 +
    'OneDrive syncs and can dehydrate or empty files under its tree. Smart Citizen '
    + 'has lost user.ini data this way (your favorited ships and custom edits live there). '
    + 'A local folder outside OneDrive is strongly recommended.' + #13#10 + #13#10 +
    'Switch to a local folder?' + #13#10 +
    '  - Click YES to use ' + Suggested + #13#10 +
    '  - Click NO to keep the OneDrive folder anyway',
    mbError, MB_YESNO);

  if Response = IDYES then
  begin
    DataDirPage.Values[0] := Suggested;
    { Stay on the page so the user sees the swapped-in local path before
      committing. Mirrors #174 keeping the user on the data-dir surface. }
    Result := False;
  end;
  { Response = IDNO: proceed with the OneDrive folder; the user was warned. }
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { 1.3.0+: the data-folder page is always shown so every user gets a
    chance to relocate the cache (not just OneDrive-synced installs). The
    OneDrive-only gate was removed — pre-fill logic in InitializeWizard
    handles the OneDrive case by suggesting a local path. }
  Result := False;
end;

