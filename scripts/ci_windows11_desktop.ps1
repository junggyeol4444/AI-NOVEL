# Windows 11 ARM64 hosted VM. Tests the x64 packaged EXE under Windows 11
# emulation in normal visible Qt mode. No user's Windows machine is involved.
# All test inputs synthetic; screenshots saved only if window is visible.
$ErrorActionPreference = "Stop"
$exe = (Resolve-Path $args[0]).Path
if (-not [Environment]::OSVersion.VersionString.Contains("Windows")) { throw "Not Windows" }
$os = Get-CimInstance Win32_OperatingSystem
Write-Host ("OS={0}; Version={1}; Architecture={2}" -f $os.Caption, $os.Version, $env:PROCESSOR_ARCHITECTURE)
if ($os.Caption -notmatch "Windows 11") { throw "This job did not run on Windows 11" }
if ($env:PROCESSOR_ARCHITECTURE -ne 'ARM64') { throw "Expected Windows 11 ARM64 runner" }
if (-not (Test-Path $exe)) { throw "EXE missing" }
$env:QT_QPA_PLATFORM = 'windows'
$proc = Start-Process -FilePath $exe -PassThru
try {
  $hwnd = [IntPtr]::Zero
  for ($i=0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    $proc.Refresh()
    if ($proc.HasExited) { throw ("Packaged EXE exited unexpectedly with " + $proc.ExitCode) }
    if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {
      $hwnd = $proc.MainWindowHandle
      break
    }
  }
  if ($hwnd -eq [IntPtr]::Zero) { throw 'No real desktop window exposed: cannot claim visual or interactive verification' }
  Write-Host ("NativeMainWindowHandle={0}; Title={1}" -f $hwnd, $proc.MainWindowTitle)
  if ($proc.MainWindowTitle -notmatch 'AI Novel Factory') { throw 'Wrong main window title' }
  Add-Type -AssemblyName UIAutomationClient
  $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
  if ($null -eq $root) { throw 'Windows UIAutomation could not attach to the Qt EXE' }
  $wanted = @('작품', 'Novel Bible', 'Characters', 'World', 'Timeline', 'Relationships', 'Foreshadowing', 'Reference Novels', 'Reference Patterns', 'Episodes', 'Similarity Reports', 'Publication')
  $found = 0
  $clicks = 0
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($entry in $all) {
    $pattern = $null
    $name = $entry.Current.Name
    if ($name -and $wanted -contains $name) {
      $found++
      if ($entry.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) {
        ([System.Windows.Automation.SelectionItemPattern]$pattern).Select()
        Start-Sleep -Milliseconds 125
        $clicks++
      }
    }
  }
  Write-Host ("AutomationElements={0}; MatchedMenuItems={1}; NativeSelectionClicks={2}" -f $all.Count, $found, $clicks)
  if ($clicks -lt 12) {
    throw "Windows UIAutomation failed to select all twelve visible sidebar pages; this is NOT a passing GUI review"
  }
  # Capture the actual interactive Windows desktop, not an offscreen Qt rendering.
  Add-Type -AssemblyName System.Drawing
  Add-Type -AssemblyName System.Windows.Forms
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  if ($bounds.Width -lt 800 -or $bounds.Height -lt 600) { throw 'No usable interactive display' }
  $bitmap = [System.Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    } finally { $graphics.Dispose() }
    New-Item -ItemType Directory -Force build/ci/windows11 | Out-Null
    $bitmap.Save((Join-Path (Get-Location).Path 'build/ci/windows11/actual_desktop.png'),
                 [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $bitmap.Dispose() }
  Write-Host 'PASS: Windows 11 desktop EXE visible, Windows UIAutomation selected 12 pages, screenshot captured.'
} finally {
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
}
