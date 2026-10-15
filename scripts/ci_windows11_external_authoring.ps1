# Native Windows 11 UI Automation acceptance. NO in-process Python/Qt
# test methods, no internal app API, no direct database writes.
# Drives the real packaged EXE exclusively through OS accessibility patterns.
# The test accepts no user credentials or manuscripts and uses only synthetic data.
param([Parameter(Mandatory=$true)][string]$ExePath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$exe = (Resolve-Path $ExePath).Path
$os = Get-CimInstance Win32_OperatingSystem
if ($os.Caption -notmatch 'Windows 11') { throw 'This native user test requires Windows 11' }
$folder = Join-Path (Get-Location).Path 'build/ci/windows11-native-user'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$database = Join-Path $folder 'synthetic_user_journey.sqlite'
if (Test-Path $database) { throw 'Would not overwrite existing test database' }
$env:QT_QPA_PLATFORM = 'windows'
$proc = Start-Process -FilePath $exe -PassThru
$steps = [System.Collections.Generic.List[object]]::new()
$completed = $false
$window = $null
function Step([string]$key,[bool]$condition) {
  $steps.Add(@{step=$key;result=$(if($condition){'PASS'}else{'FAIL'})})
  Write-Host ("EXTERNAL_WINDOWS11_GUI_STEP " + $key + "=" + $(if($condition){'PASS'}else{'FAIL'}))
  if (-not $condition) { throw "Native external UI automation step failed: $key" }
}
function Element([System.Windows.Automation.AutomationElement]$root,[string]$automationId) {
  $condition = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $automationId)
  $item = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$condition)
  if ($null -ne $item) { return $item }
  # Real Qt on Windows 11 may provide NO AutomationId even when objectName is
  # set. Use the localized accessible name and semantic control type instead.
  $displayName = @{
    studioAdvancedButton = '세부 작업 도구'
    studioNewButton = '새 작품 만들기'
    studioNewTitle = '작품 제목 *'
    studioNewAuthor = '작가/필명'
    studioNewGenre = '장르'
    studioNewSubject = '소재와 주인공'
    studioNewPremise = '최상위 작품 설정'
    studioCreateProjectButton = '로컬 작품 생성'
    studioFirstEpisodeButton = '첫 회차 바로 시작'
    studioManuscriptEditor = '회차 원고 편집기'
    studioSaveManuscript = '원고 버전 저장'
    authoring_db = '로컬 DB 파일 경로'
    authoring_title = '작품 제목'
    authoring_author = '작가 이름'
    authoring_premise = '최상위 설정'
    authoring_genre = '장르'
    authoring_subject = '소재/핵심 아이디어'
    authoring_target_episodes = '목표 회차 수 (1~1000000)'
    authoring_characters_per_episode = '회차당 목표 글자 수'
    authoring_mood = '분위기'
    authoring_bible = '설정'
    createProjectButton = '새 작품 생성'
    authoring_save_bible = '설정 저장'
    openAuthoringProjectButton = '기존 작품 열기'
  }[$automationId]
  if (-not $displayName) { return $null }
  $cond = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty, $displayName)
  $matches = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
  $wantButton = $automationId -in @('studioAdvancedButton','studioNewButton','studioCreateProjectButton','studioFirstEpisodeButton','studioSaveManuscript') -or $automationId -eq 'createProjectButton' -or
                $automationId -eq 'authoring_save_bible' -or
                $automationId -eq 'openAuthoringProjectButton'
  foreach ($candidate in $matches) {
    $t = $candidate.Current.ControlType.ProgrammaticName
    if ($wantButton -and $t -like '*Button') { return $candidate }
    if (-not $wantButton -and ($t -like '*Edit' -or $t -like '*Document')) {
      return $candidate
    }
  }
  return $null
}
function Set-AccessibleText([System.Windows.Automation.AutomationElement]$root,
                            [string]$automationId,[string]$value) {
  $control = Element $root $automationId
  Step ("present_"+$automationId) ($null -ne $control)
  $valuePattern = $null
  $hasValue = $control.TryGetCurrentPattern(
    [System.Windows.Automation.ValuePattern]::Pattern,[ref]$valuePattern)
  Step ("value_pattern_"+$automationId) ($hasValue)
  ([System.Windows.Automation.ValuePattern]$valuePattern).SetValue($value)
  Start-Sleep -Milliseconds 250
  $current = ([System.Windows.Automation.ValuePattern]$valuePattern).Current.Value
  Step ("input_persisted_in_gui_"+$automationId) ($current -eq $value)
}
function Invoke-Accessible([System.Windows.Automation.AutomationElement]$root,
                           [string]$automationId) {
  $control = Element $root $automationId
  Step ("button_present_"+$automationId) ($null -ne $control)
  $pattern = $null
  $supported = $control.TryGetCurrentPattern(
     [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)
  Step ("invoke_pattern_"+$automationId) ($supported)
  ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
  Start-Sleep -Milliseconds 400
}
try {
  $handle = [IntPtr]::Zero
  for ($i=0;$i -lt 65;$i++) {
    Start-Sleep -Seconds 1
    $proc.Refresh()
    if ($proc.HasExited) { throw ('Packaged EXE exited before user actions: '+$proc.ExitCode) }
    foreach ($candidate in @(Get-Process -Name AI_Novel_Factory -ErrorAction SilentlyContinue)) {
      $candidate.Refresh()
      if ($candidate.MainWindowHandle -ne [IntPtr]::Zero -and
          $candidate.MainWindowTitle -match 'AI Novel Factory') {
        $handle = $candidate.MainWindowHandle
        break
      }
    }
    if ($handle -ne [IntPtr]::Zero) { break }
  }
  Step 'external_windows11_real_exe_window' ($handle -ne [IntPtr]::Zero)
  $window = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
  Step 'native_uia_window_connection' ($null -ne $window)

  # Log ONLY safe widget identifiers if an accessibility field is missing.
  # Never log values because those could be manuscript or credential fields.
  $ids = [System.Collections.Generic.List[string]]::new()
  foreach ($control in $window.FindAll(
      [System.Windows.Automation.TreeScope]::Descendants,
      [System.Windows.Automation.Condition]::TrueCondition)) {
    $id = $control.Current.AutomationId
    if ($id -and $id -like 'authoring*' -and $ids.Count -lt 55) {
      $ids.Add($id)
    }
  }
  Write-Host ('External UIA authoring control identifiers: '+($ids -join ', '))
  # Safe accessibility diagnostics: do not log actual text field values.
  $sample = [System.Collections.Generic.List[string]]::new()
  foreach ($candidate in $window.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)) {
    $candidateName = $candidate.Current.Name
    if ($candidateName -and $sample.Count -lt 90) {
      $type = $candidate.Current.ControlType.ProgrammaticName
      $sample.Add(($type + ':' + $candidateName).Substring(
        0, [Math]::Min(125, ($type + ':' + $candidateName).Length)))
    }
  }
  Write-Host ('External UIA safe control labels: '+($sample -join ' | '))

  # Independently exercise the new default user-facing project flow, by OS
  # accessibility (no Python Qt method calls or direct SQLite writes).
  Invoke-Accessible $window 'studioNewButton'
  Set-AccessibleText $window 'studioNewTitle' 'Synthetic Studio Windows11 Novel'
  Set-AccessibleText $window 'studioNewAuthor' 'Original Synthetic Author'
  Set-AccessibleText $window 'studioNewGenre' 'fantasy'
  Set-AccessibleText $window 'studioNewSubject' 'An invented clockwork valley'
  Set-AccessibleText $window 'studioNewPremise' 'Original characters only'
  Invoke-Accessible $window 'studioCreateProjectButton'
  $titleCheck = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    'Synthetic Studio Windows11 Novel')
  Step 'native_studio_created_selected_project' (
    $null -ne $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $titleCheck))

  Invoke-Accessible $window 'studioFirstEpisodeButton'
  Set-AccessibleText $window 'studioManuscriptEditor' 'Original synthetic test manuscript; first chapter'
  Invoke-Accessible $window 'studioSaveManuscript'
  $savedLabel = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    '로컬 SQLite에 새 원고 버전을 저장했습니다. 자동 검수는 별도입니다.')
  Step 'native_studio_writer_saved_real_version_through_button' (
    $null -ne $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $savedLabel))

  Invoke-Accessible $window 'studioAdvancedButton'
  Set-AccessibleText $window 'authoring_db' $database
  Set-AccessibleText $window 'authoring_title' 'Synthetic Windows 11 Novel'
  Set-AccessibleText $window 'authoring_author' 'Synthetic Test Author'
  Set-AccessibleText $window 'authoring_premise' 'Only original fictional characters and villages'
  Set-AccessibleText $window 'authoring_genre' 'fantasy'
  Set-AccessibleText $window 'authoring_subject' 'An invented lantern village'
  Set-AccessibleText $window 'authoring_target_episodes' '2'
  Set-AccessibleText $window 'authoring_characters_per_episode' '120'
  Set-AccessibleText $window 'authoring_mood' 'mystery'
  Invoke-Accessible $window 'createProjectButton'
  $dbCreated = $false
  for ($i=0;$i -lt 20;$i++) {
    Start-Sleep -Milliseconds 400
    if (Test-Path $database) {
      $dbCreated = (Get-Item $database).Length -gt 1000
      if ($dbCreated) { break }
    }
  }
  Step 'external_gui_create_click_wrote_real_sqlite' $dbCreated

  # Enter and save the Novel Bible via the application GUI, not SQL.
  Set-AccessibleText $window 'authoring_bible' 'Original fictional bridge and secret lantern; synthetic canon only'
  Invoke-Accessible $window 'authoring_save_bible'
  Step 'external_gui_clicked_save_bible' ((Test-Path $database) -and
           (Get-Item $database).Length -gt 1000)

  # The Windows 11 user-facing QA job must not need installed Python.
  # Inspect the native SQLite database header using built-in .NET only.
  # SQLite may keep an open WAL/shared DB handle while the application runs.
  # Open the header with FileShare.ReadWrite, not File.OpenRead's restrictive
  # Read-only sharing mode. This must never require closing the user's app.
  $stream = [System.IO.FileStream]::new(
    $database, [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $header = [byte[]]::new(16)
    $read = $stream.Read($header,0,16)
  } finally { $stream.Dispose() }
  $magic = [System.Text.Encoding]::ASCII.GetString($header)
  Step 'external_sqlite_header_verified_without_python' (
    $read -eq 16 -and $magic -eq ("SQLite format 3" + [char]0))

  # A user closes the EXE and starts it again: verify the same project opens
  # through the native UIA button, with original settings and Bible restored.
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ANFGuiClose {
    [DllImport("user32.dll")] public static extern bool PostMessage(
       IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
'@
  Step 'external_gui_close_button_message_sent' ([ANFGuiClose]::PostMessage(
    $handle, [uint32]0x0010, [IntPtr]::Zero, [IntPtr]::Zero))
  $closed = $false
  for ($i=0;$i -lt 60;$i++) {
    Start-Sleep -Milliseconds 300
    $proc.Refresh()
    if ($proc.HasExited) { $closed = $true; break }
  }
  Step 'external_gui_first_exe_closed_cleanly' $closed
  $reopenedProc = Start-Process -FilePath $exe -PassThru
  try {
    $newHwnd = [IntPtr]::Zero
    for ($i=0;$i -lt 60;$i++) {
      Start-Sleep -Milliseconds 400
      $reopenedProc.Refresh()
      if ($reopenedProc.HasExited) {
        throw 'Standalone reopened GUI EXE unexpectedly exited'
      }
      foreach ($candidate in @(Get-Process -Name AI_Novel_Factory -ErrorAction SilentlyContinue)) {
        $candidate.Refresh()
        if ($candidate.MainWindowHandle -ne [IntPtr]::Zero -and
            $candidate.MainWindowHandle -ne $handle -and
            $candidate.MainWindowTitle -match 'AI Novel Factory') {
          $newHwnd = $candidate.MainWindowHandle
          break
        }
      }
      if ($newHwnd -ne [IntPtr]::Zero) { break }
    }
    Step 'external_gui_separate_exe_restarted' ($newHwnd -ne [IntPtr]::Zero)
    $newWindow = [System.Windows.Automation.AutomationElement]::FromHandle($newHwnd)
    Invoke-Accessible $newWindow 'studioAdvancedButton'
    Set-AccessibleText $newWindow 'authoring_db' $database
    Invoke-Accessible $newWindow 'openAuthoringProjectButton'
    Start-Sleep -Milliseconds 500
    $values = @{}
    foreach ($field in @('authoring_title','authoring_genre','authoring_bible')) {
      $el = Element $newWindow $field
      Step ("reopened_input_"+$field) ($null -ne $el)
      $pattern = $null
      Step ("reopened_value_pattern_"+$field) ($el.TryGetCurrentPattern(
        [System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern))
      $values[$field] = ([System.Windows.Automation.ValuePattern]$pattern).Current.Value
    }
    Step 'external_user_reopened_saved_novel_from_real_gui' (
       $values['authoring_title'] -eq 'Synthetic Windows 11 Novel' -and
       $values['authoring_genre'] -eq 'fantasy' -and
       $values['authoring_bible'] -eq 'Original fictional bridge and secret lantern; synthetic canon only')
  } finally {
    if ($reopenedProc -and -not $reopenedProc.HasExited) {
      Stop-Process -Id $reopenedProc.Id -Force -ErrorAction SilentlyContinue
    }
  }
  $completed = $true
} catch {
  Write-Host ('EXTERNAL_GUI_TEST_FAILURE_CATEGORY '+$_.Exception.GetType().Name)
  # exception messages only originate from our own non-sensitive step labels;
  # no real title, draft, filepath or model prompt is included in report.
  throw
} finally {
  $report = @{
    test = 'WIN11_EXTERNAL_OS_UIA_REAL_EXE_SYNTHETIC_USER'
    result = $(if($completed){'PASS'}else{'FAIL'})
    steps = $steps.ToArray()
    native_desktop_foreground_review = 'NOT_CLAIMED'
    use_of_in_process_qt_test_methods = $false
    user_credentials_or_manuscripts = $false
  }
  $report | ConvertTo-Json -Depth 8 |
     Set-Content -Path (Join-Path $folder 'external_user_report.json') -Encoding utf8
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
}
