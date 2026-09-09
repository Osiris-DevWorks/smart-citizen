; Single source of truth: VERSION.TXT at the project root. Update that file
; and re-run the build — every version-stamped field below is derived from it.
#define VersionFile FileOpen(AddBackslash(SourcePath) + "VERSION.TXT")
#define AppVer Trim(FileRead(VersionFile))
#expr FileClose(VersionFile)
#undef VersionFile

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
; #211 in-app auto-update: relaunch Smart Citizen after a silent upgrade. The
; postinstall entry above only fires from the finish page, which a /SILENT
; install never shows. Gated on the /AUTOUPDATE=1 switch the app passes, so
; manual silent installs are unaffected. runasoriginaluser is required: the
; installer runs elevated, and without it the relaunched app would run as
; admin (and write user.ini / caches with admin ownership).
Filename: "{app}\SmartCitizen.exe"; Flags: nowait runasoriginaluser; Check: IsAutoUpdate

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

function IsAutoUpdate(): Boolean;
begin
  { True when this install was spawned by the app's in-app auto-updater
    (#211), which passes /AUTOUPDATE=1 — see _launch_installer_and_quit in
    src/gui/main_window.py. Drives the [Run] entry that relaunches the app
    after a silent upgrade. }
  Result := ExpandConstant('{param:AUTOUPDATE|0}') = '1';
end;

function IsVerySilentUninstall(): Boolean;
var
  I: Integer;
begin
  { #357 review fix: UninstallSilent() is True for BOTH /SILENT and
    /VERYSILENT, but only /VERYSILENT means genuinely headless -- /SILENT
    still shows MsgBox prompts, and the "click NO, uninstall old version
    only" branch of the reinstall-detection prompt below runs its
    sub-uninstall with exactly /SILENT (an interactive user is sitting
    right there, mid-click). Checking the actual command line instead of
    UninstallSilent() distinguishes that case from the truly automated
    /VERYSILENT auto-update cleanup (UnInstallOldVersion above). }
  Result := False;
  for I := 1 to ParamCount do
  begin
    if CompareText(ParamStr(I), '/VERYSILENT') = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
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
  { #357: override-aware resolver for the DataForge cache location, mirroring
    GetDocumentsDir's resolution order for user_data_dir. Needed so the
    opt-in full-wipe uninstall (DeleteAllUserSettings) deletes wherever the
    cache ACTUALLY lives, not just the %LOCALAPPDATA% default -- a user who
    moved it to another drive would otherwise be left with a multi-GB
    orphaned folder after "delete everything". }
  if RegQueryStringValue(HKCU,
    'Software\Osiris DevWorks\Smart Citizen',
    'cache_dir', OverridePath) and (OverridePath <> '') then
  begin
    Result := OverridePath;
    Exit;
  end;
  Result := GetLocalCacheDefault();
end;

function IsDocsOnOneDrive(): Boolean;
var
  DocsPath: String;
begin
  { Read the invoking user's Documents shell-folder path. When Windows has
    folder-redirected Documents into OneDrive (the default on most OneDrive
    installs now), this string contains "\OneDrive\". Cache extraction +
    50,000-file rmtree under an actively-synced OneDrive tree is 3-5x
    slower and routinely fails with WinError 5 — worth warning the user
    and offering a local-only alternative. }
  Result := False;
  if RegQueryStringValue(HKCU,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    'Personal', DocsPath) then
  begin
    Result := (Pos('\OneDrive\', DocsPath) > 0) or
              (Pos('\OneDrive/', DocsPath) > 0);
  end;
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
  Remaining, Seg: String;
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

  Roots[0] := GetEnv('OneDrive');
  Roots[1] := GetEnv('OneDriveConsumer');
  Roots[2] := GetEnv('OneDriveCommercial');
  for i := 0 to 2 do
  begin
    if PathUnderRoot(Path, Roots[i]) then
    begin
      Result := True;
      Exit;
    end;
  end;

  { Segment fallback: split on '\' and test each component. }
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
    if IsOneDriveSegment(Seg) then
    begin
      Result := True;
      Exit;
    end;
  end;
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
      state days later when Apps & Features had no entry. }
    if WaitForUninstallerCleanup(sUnInstallString, 180) then
      Log('Old uninstaller cleanup finished.')
    else
    begin
      Log('WARNING: timed out waiting for old uninstaller to finish (180s). The new install may produce a broken uninstaller; user should uninstall + reinstall manually if the Apps & Features entry is missing.');
      MsgBox('The previous version''s uninstaller did not finish within 3 minutes.' + #13#10 + #13#10 +
             'The install will continue, but the new uninstaller file (unins000.exe) may be deleted by the old uninstaller''s delayed cleanup. If that happens, Smart Citizen will install successfully but will not appear in Apps & Features.' + #13#10 + #13#10 +
             'If you later cannot uninstall Smart Citizen, re-run this installer and choose the Uninstall option, or delete the install folder manually.' + #13#10 + #13#10 +
             'Closing other apps (especially OneDrive sync, antivirus scans, and the Search Indexer) before the install can avoid this.',
             mbError, MB_OK);
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
    'Software\Osiris DevWorks\Smart Citizen',
    'user_data_dir', OverridePath) and (OverridePath <> '') then
  begin
    Result := OverridePath;
    Exit;
  end;
  Result := GetDocumentsBase() + '\Smart Citizen';
end;

procedure MigrateUserDocsFolder();
var
  DocsBase, OldDir, NewDir: String;
begin
  { Rebrand: rename Documents\SC Localization Editor\ → Documents\Smart Citizen\
    if the old folder exists and the new one does not. User data (user.ini,
    backups, cache) moves with the rename — no copy required. }
  DocsBase := GetDocumentsBase();
  OldDir := DocsBase + '\SC Localization Editor';
  NewDir := DocsBase + '\Smart Citizen';
  if DirExists(OldDir) and not DirExists(NewDir) then
  begin
    MsgBox('Your user data folder will be renamed as part of this update:' + #13#10 + #13#10 +
           '  ' + OldDir + #13#10 +
           '  →  ' + NewDir + #13#10 + #13#10 +
           'Your custom edits, backups, and cached files will move with it — nothing is lost.',
           mbInformation, MB_OK);
    Log('Renaming user data folder: ' + OldDir + ' -> ' + NewDir);
    if not RenameFile(OldDir, NewDir) then
      Log('WARNING: rename failed; data remains at old location');
  end;
end;

procedure CleanPerChannelCaches(UserDataDir: String);
var
  Channels: array[0..4] of String;
  i: Integer;
  CachePath: String;
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
    log so users reporting "cache wasn't removed" can be diagnosed. }
  Channels[0] := 'LIVE';
  Channels[1] := 'PTU';
  Channels[2] := 'EPTU';
  Channels[3] := 'HOTFIX';
  Channels[4] := 'TECH-PREVIEW';
  for i := 0 to 4 do
  begin
    CachePath := UserDataDir + '\' + Channels[i] + '\cache';
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
  UserDataDir, LegacyCache: String;
begin
  UserDataDir := GetDocumentsDir();
  if DirExists(UserDataDir) then
  begin
    Log('Cleaning cached data from: ' + UserDataDir);
    { Current layout — delete \cache under each channel subtree. }
    CleanPerChannelCaches(UserDataDir);
    { Defensive: pre-0.9.3 flat layout kept cache at \Smart Citizen\cache\.
      The channel migrator runs at app launch and should have moved this
      already, but if a user is upgrading from a state where the migrator
      never ran (e.g. they uninstalled before first launching 0.9.3+),
      mop it up here. }
    LegacyCache := UserDataDir + '\cache';
    if DirExists(LegacyCache) then
    begin
      Log('Deleting legacy flat-layout cache: ' + LegacyCache);
      DelTree(LegacyCache, True, True, True);
    end;
  end;
end;

{ Persistence contract (#172): the user's data-folder choice must survive
  uninstall + reinstall. It does so by construction —
    - user_data_dir is written to the LIVE node (Osiris DevWorks\Smart Citizen)
      via RegWriteStringValue in WriteInstallerChoicesToRegistry, NOT via a
      Registry-section entry, so Inno's own uninstaller has no value to drop;
    - this script has no Registry section and no code path that deletes
      values from the live node, so nothing wipes it on uninstall;
    - InitializeWizard pre-fills user_data_dir on the next install.
  The real risk vector is a FUTURE change adding live-node deletion to the
  uninstall step (see CurUninstallStepChanged). A former CleanRegistrySettings()
  helper that key-deleted a whole node lived here and was dead code; it was
  removed deliberately so its wipe pattern can't be copied and retargeted at
  the live node. Do not reintroduce node/value deletion against
  'Software\Osiris DevWorks\Smart Citizen' in the uninstall path. }

procedure WriteInstallerChoicesToRegistry();
var
  RegPath: String;
  FinalPath: String;
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
    RegPath := 'Software\Osiris DevWorks\Smart Citizen';
    RegWriteStringValue(HKCU, RegPath, 'sc_directory', FinalPath);
    RegWriteStringValue(HKCU, RegPath, 'game_install_path', FinalPath);
    { Write sc_install_root (parent of the channel folder) so a reinstall
      with a changed SC path doesn't leave the stale root from a prior
      migration winning over the freshly chosen directory. }
    RegWriteStringValue(HKCU, RegPath, 'sc_install_root', ExtractFileDir(RemoveBackslash(FinalPath)));
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\SC Localization Editor',
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
  DocsDefault := GetDocumentsBase() + '\Smart Citizen';
  if (DataDir = '') or (CompareText(DataDir, DocsDefault) = 0) then
  begin
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'user_data_dir');
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'UserDataDir');
    Log('User chose default Documents folder; cleared user_data_dir override.');
  end
  else
  begin
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen',
      'user_data_dir', DataDir);
    RegDeleteValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'UserDataDir');
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
      'Software\Osiris DevWorks\Smart Citizen', 'cache_dir');
    Log('User chose default cache folder; cleared cache_dir override.');
  end
  else
  begin
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen',
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
      'Software\Osiris DevWorks\Smart Citizen', 'ui_mode', 'advanced')
  else
    RegWriteStringValue(HKCU,
      'Software\Osiris DevWorks\Smart Citizen', 'ui_mode', 'simple');
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
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'french');
      2: RegWriteStringValue(HKCU,
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'portuguese_br');
      3: RegWriteStringValue(HKCU,
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'spanish');
      4: RegWriteStringValue(HKCU,
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'japanese');
      5: RegWriteStringValue(HKCU,
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'chinese');
      6: RegWriteStringValue(HKCU,
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'italian');
      7: RegWriteStringValue(HKCU,
           'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'german');
    else
      RegWriteStringValue(HKCU,
        'Software\Osiris DevWorks\Smart Citizen', 'selected_language', 'english');
    end;
    Log('Saved selected_language to registry.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
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

procedure DeleteAllUserSettings();
var
  UserDataDir, CacheDir, LegacyUserDataDir: String;
begin
  { #357: the ONE deliberate exception to the #172 persistence lock
    documented in CurUninstallStepChanged below — only reached when the
    user explicitly ticked "also delete all saved settings" on the custom
    uninstall confirmation dialog (see InitializeUninstall). Removes the
    three locations the app's settings/data can live in:
      1. HKCU registry node (sc_directory, user_data_dir, cache_dir,
         ui_mode, selected_language, the owned-blueprints set, everything
         AppSettings persists in registry mode).
      2. The user data folder (user.ini, backups, per-channel cache) —
         wherever it ACTUALLY resolves to, matching GetDocumentsDir's own
         override-aware resolution, not just the Documents default.
      3. The separate DataForge cache folder (~1.4 GB) — wherever it
         ACTUALLY resolves to (GetCacheDir). This one is never touched by
         the normal uninstall path at all (CleanCachedData only ever
         reaches into the user data folder's per-channel \cache
         subfolders), so leaving it out here would defeat the point of a
         "full" wipe for anyone who moved it to a custom drive.
    Path resolution happens BEFORE the registry delete on purpose: both
    overrides (user_data_dir / cache_dir) live in that registry node, so
    deleting it first would make GetDocumentsDir/GetCacheDir fall back to
    the wrong (default) location and silently miss a custom folder. }
  Log('User opted in to full settings wipe (issue #357).');

  UserDataDir := GetDocumentsDir();
  CacheDir := GetCacheDir();

  if DirExists(UserDataDir) then
  begin
    Log('Deleting user data folder: ' + UserDataDir);
    if not DelTree(UserDataDir, True, True, True) then
      Log('WARNING: DelTree returned false for user data folder: ' + UserDataDir);
  end
  else
    Log('User data folder absent (nothing to delete): ' + UserDataDir);

  { #357 review: the pre-0.9.0, pre-rebrand Documents folder (mirrors
    MigrateUserDocsFolder's OldDir). GetDocumentsDir() only ever resolves to
    the current "Smart Citizen" name -- an install that never launched a
    post-rebrand build (so the migration rename never ran) would otherwise
    keep its old user.ini/backups/cache here even after a "full wipe". Not
    gated on user_data_dir being unset: the rename is unconditional on the
    Documents base, independent of whether a later version's override is
    also in play, so this folder can exist (or not) regardless. }
  LegacyUserDataDir := GetDocumentsBase() + '\SC Localization Editor';
  if DirExists(LegacyUserDataDir) then
  begin
    Log('Deleting legacy pre-rebrand user data folder: ' + LegacyUserDataDir);
    if not DelTree(LegacyUserDataDir, True, True, True) then
      Log('WARNING: DelTree returned false for legacy user data folder: ' + LegacyUserDataDir);
  end;

  { Skip if it's the same folder as (or nested under) the user data folder
    already just deleted above -- a custom cache_dir is normally a wholly
    separate location, but avoid a redundant/confusing second DelTree pass
    over the same path either way. PathUnderRoot covers both cases: it
    matches an exact match too, since normalizing both sides the same way
    before the prefix test makes a path trivially "under" itself. }
  if (CacheDir <> '') and (not PathUnderRoot(CacheDir, UserDataDir)) then
  begin
    if DirExists(CacheDir) then
    begin
      Log('Deleting DataForge cache folder: ' + CacheDir);
      if not DelTree(CacheDir, True, True, True) then
        Log('WARNING: DelTree returned false for cache folder: ' + CacheDir);
    end
    else
      Log('DataForge cache folder absent (nothing to delete): ' + CacheDir);
  end;

  if RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Osiris DevWorks\Smart Citizen') then
    Log('Deleted HKCU registry node: Software\Osiris DevWorks\Smart Citizen')
  else
    Log('HKCU registry node delete returned false (may already be absent).');
  { Legacy pre-rebrand node, in case an ancient install never migrated. }
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Osiris DevWorks\SC Localization Editor');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if DeleteAllSettingsChecked then
    begin
      { #357: user explicitly opted in via the uninstall confirmation
        dialog's checkbox -- see DeleteAllUserSettings for what this
        deletes and why it supersedes the normal CleanCachedData() call
        below (it deletes the whole user data folder, a superset of the
        per-channel \cache CleanCachedData targets). }
      DeleteAllUserSettings();
    end
    else
    begin
      { Same cleanup contract as install/upgrade: per-channel \cache gets
        nuked, \backups + user.ini survive so a reinstall picks up where
        the user left off. Only \cache is disposable.

        Persistence lock (#172): do NOT delete the live registry node
        'Software\Osiris DevWorks\Smart Citizen' or any of its values here —
        user_data_dir (and the other settings) MUST survive uninstall so the
        next install pre-fills the user's chosen data folder. Wiping the node
        is exactly the regression that let the data-folder choice revert.
        (The one deliberate exception is DeleteAllUserSettings above, gated
        on the user's explicit opt-in checkbox — issue #357 — every other
        path through here, this branch, leaves the node untouched.) }
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
  { #357: the warning is delivered here, as an explicit acknowledge-to-
    proceed popup fired the moment the box is TICKED, rather than as
    passive text sitting on the main dialog (easy to skim past, and — per
    the first version of this dialog — it also doesn't fit: TNewCheckBox
    doesn't word-wrap its caption, so a long inline warning either got
    clipped or ran off the dialog entirely). Sender is the checkbox itself,
    since this is wired up as its OnClick handler below. }
  CB := TNewCheckBox(Sender);
  if not CB.Checked then
    Exit;  { Only warn on the OFF -> ON transition; unchecking needs no prompt. }

  Response := MsgBox(
    'This will permanently delete:' + #13#10 +
    '  - Your saved Star Citizen directory and other settings (registry)' + #13#10 +
    '  - Your user data folder (custom edits, owned blueprints list, backups)' + #13#10 +
    '  - The cached DataForge data' + #13#10 + #13#10 +
    'This cannot be undone. Click OK to confirm, or Cancel to keep your settings.',
    mbError, MB_OKCANCEL);
  if Response <> IDOK then
    CB.Checked := False;  { Not acknowledged -- revert to the safe default. }
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

  { #357: never show the custom dialog during a truly headless uninstall --
    e.g. the old-version cleanup step of an in-app auto-update, which runs
    its uninstaller with /VERYSILENT (see UnInstallOldVersion above and
    _launch_installer_and_quit in src/gui/main_window.py). Unlike MsgBox, a
    raw custom VCL form isn't auto-suppressed by Inno's silent flags, so
    skipping it here is required — otherwise a fully automated upgrade
    would hang forever waiting for a click on a dialog nobody can see.
    Defaults to False (the safe, non-destructive choice): an
    automated/background uninstall must never accidentally wipe settings.

    Deliberately checks IsVerySilentUninstall(), not UninstallSilent():
    the latter is also True for plain /SILENT, which the interactive
    "click NO, uninstall old version only" reinstall-detection flow further
    below uses for its sub-uninstall -- that's a user sitting at the
    installer mid-click, not a headless run, and skipping the dialog there
    would silently deny them the choice this feature exists to offer. }
  if IsVerySilentUninstall() then
    Exit;

  { Fixed size (AAllowResize=False): a static confirmation dialog has no
    controls that benefit from resizing. DoubleBuffered=True for smooth
    rendering, matching CreateCustomForm's documented example usage. }
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
    MsgLabel.Caption := 'Are you sure you want to uninstall Smart Citizen?';

    { Short, single-line caption on purpose: TNewCheckBox renders its
      Caption as one line and clips anything that doesn't fit, unlike
      TNewStaticText -- the full explanation lives in the acknowledge
      popup (DeleteAllCheckBoxOnClick) instead. }
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
      { By the time we get here, a checked box has already been through
        the acknowledge popup above (and would have reverted to
        unchecked if not confirmed) -- no need to re-warn on this click. }
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

    { Show custom dialog with three options }
    ButtonPressed := MsgBox('A previous version of this application is already installed.' + #13#10 + #13#10 +
                            'Choose an option:' + #13#10 +
                            '  - Click YES to uninstall the old version and install this new version' + #13#10 +
                            '  - Click NO to uninstall the old version only (without installing)' + #13#10 +
                            '  - Click CANCEL to exit without making any changes',
                            mbConfirmation, MB_YESNOCANCEL);

    case ButtonPressed of
      IDYES: begin
        { Continue with upgrade (uninstall old, then install new) }
        Result := True;
      end;
      IDNO: begin
        { Uninstall only, without installing new version }
        UninstallString := RemoveQuotes(UninstallString);
        Exec(UninstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Result := False;
      end;
      IDCANCEL: begin
        { Cancel installation }
        Result := False;
      end;
    end;
  end;
end;

function IsValidSCPath(const Path: String): Boolean;
var
  BasePath: String;
  LastName: String;
begin
  { Returns True if Path looks like a valid Star Citizen install path.
    Accepts either:
      - a root containing channel subdirectories (LIVE, PTU, etc.), or
      - a channel path (last component is a channel name like LIVE).
    Guards against stale registry values like 'SmartCitizen 1.4.1'. }
  BasePath := RemoveBackslash(Path) + '\';
  LastName := LowerCase(ExtractFileName(BasePath));
  if (LastName = 'live') or (LastName = 'ptu') or (LastName = 'eptu') or
     (LastName = 'hotfix') or (LastName = 'tech-preview') then
    Result := True
  else
    Result := DirExists(BasePath + 'LIVE') or DirExists(BasePath + 'PTU') or
              DirExists(BasePath + 'EPTU') or DirExists(BasePath + 'HOTFIX') or
              DirExists(BasePath + 'TECH-PREVIEW');
end;

procedure InitializeWizard();
var
  NewRegPath: String;
  LegacyRegPath: String;
  DefaultPath: String;
  SavedPath: String;
  SCRoot: String;
  ActiveChannel: String;
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

  { Pre-select the prior choice on a reinstall so an upgrade doesn't
    silently reset a non-English user back to English. Defaults to
    English (index 0) when nothing is saved yet or the saved value
    doesn't match a known option. }
  LanguageIndex := 0;
  LanguageChoiceUnknownSaved := False;
  if RegQueryStringValue(HKCU, 'Software\Osiris DevWorks\Smart Citizen',
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
  NewRegPath := 'Software\Osiris DevWorks\Smart Citizen';
  LegacyRegPath := 'Software\Osiris DevWorks\SC Localization Editor';
  DefaultPath := '';

  { 0.9.3+: the app stores the SC install root (parent of LIVE/PTU/...) in
    sc_install_root. Always default the installer's prompt to the LIVE
    subfolder — the page title says "Star Citizen LIVE Directory" and
    users consistently expect LIVE to be offered regardless of which
    channel the app is currently pointed at. The active_channel value is
    ignored here on purpose; the app-side channel switcher handles
    per-channel paths at runtime. }
  if RegQueryStringValue(HKCU, NewRegPath, 'sc_install_root', SCRoot) and (SCRoot <> '') and IsValidSCPath(SCRoot) then
  begin
    ActiveChannel := 'LIVE';
    DefaultPath := SCRoot + '\' + ActiveChannel;
  end;

  { Fall back to previously saved sc_directory / game_install_path in the
    NEW node, then the LEGACY node.  Each value is validated to ensure it
    actually looks like a valid SC install path (either ends with a channel
    name, or contains channel subdirectories).  Validation is folded into
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
    as the default confuses users whose main SC install is LIVE. }
  if LowerCase(ExtractFileName(DefaultPath)) = 'ptu' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE'
  else if LowerCase(ExtractFileName(DefaultPath)) = 'eptu' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE'
  else if LowerCase(ExtractFileName(DefaultPath)) = 'hotfix' then
    DefaultPath := ExtractFilePath(DefaultPath) + 'LIVE'
  else if LowerCase(ExtractFileName(DefaultPath)) = 'tech-preview' then
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
      2. Else if Documents is OneDrive-synced, suggest the local
         %USERPROFILE%\Documents\Smart Citizen junction (escapes the sync).
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
    the default rather than prefilling a bad path. Issue #120. }
  if RegQueryStringValue(HKCU, NewRegPath, 'user_data_dir', SavedDataDir) and
     (SavedDataDir <> '') and not IsStalePrefill(SavedDataDir) then
    DataDirPage.Values[0] := SavedDataDir
  else if IsDocsOnOneDrive() then
    DataDirPage.Values[0] := SuggestLocalDataDir()
  else
    DataDirPage.Values[0] := GetDocumentsBase() + '\Smart Citizen';

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

