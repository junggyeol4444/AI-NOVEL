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
  return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$condition)
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

  # A simple third-party SQLite reader checks real persistence; no internal
  # Python module or Qt methods are imported into this PowerShell process.
  $pyCheck = @'
import sqlite3,sys
path=sys.argv[1]
db=sqlite3.connect(path)
tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
assert len(tables)>=3, "expected actual SQLite app schema"
assert any("project" in t.lower() for t in tables), "missing actual novel project table"
print("EXTERNAL_GUI_SQLITE_SCHEMA_PASS",len(tables))
'@
  $python = Get-Command python -ErrorAction Stop
  & $python.Source -c $pyCheck $database
  if ($LASTEXITCODE -ne 0) { throw 'Actual SQLite schema failed external validation' }
  Step 'external_sqlite_schema_verified_without_app_imports' $true
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
