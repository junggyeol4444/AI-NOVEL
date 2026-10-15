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
  $windowTitle = ''
  for ($i=0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    $proc.Refresh()
    if ($proc.HasExited) { throw ("Packaged EXE exited unexpectedly with " + $proc.ExitCode) }
    # PyInstaller --onefile starts a parent extraction/monitor process and
    # then a CHILD process that owns the Qt window. MainWindowHandle on the
    # extraction parent is typically zero even on a valid interactive desktop.
    $candidates = @(Get-Process -Name AI_Novel_Factory -ErrorAction SilentlyContinue)
    foreach ($candidate in $candidates) {
      $candidate.Refresh()
      if ($candidate.MainWindowHandle -ne [IntPtr]::Zero -and
          $candidate.MainWindowTitle -match 'AI Novel Factory') {
        $hwnd = $candidate.MainWindowHandle
        $windowTitle = $candidate.MainWindowTitle
        break
      }
    }
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) {
    $counts = @(Get-Process -Name AI_Novel_Factory -ErrorAction SilentlyContinue).Count
    Write-Host ("PyInstaller matching EXE process count=" + $counts +
                "; parent MainWindowHandle=" + $proc.MainWindowHandle)
    throw 'No real desktop window exposed by parent or child: interactive GUI acceptance UNVERIFIED'
  }
  Write-Host ("NativeMainWindowHandle={0}; Title={1}" -f $hwnd, $windowTitle)
  if ($windowTitle -notmatch 'AI Novel Factory') { throw 'Wrong main window title' }
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
  # Real Win32 window capture, independent of the Qt offscreen screenshot test.
  # On disposable hosted Windows 11, OS setup/OOBE can be in front of our EXE.
  Add-Type -AssemblyName System.Drawing
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ANFWin32 {
    [StructLayout(LayoutKind.Sequential)]
    public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int show);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetWindowPos(
        IntPtr hwnd, IntPtr order, int x, int y, int width, int height, uint flags);
}
'@
  $rect = [ANFWin32+Rect]::new()
  if (-not [ANFWin32]::GetWindowRect($hwnd, [ref]$rect)) { throw "Could not query actual Qt HWND rectangle" }
  $width = $rect.Right - $rect.Left
  $height = $rect.Bottom - $rect.Top
  if ($width -lt 760 -or $height -lt 500 -or $width -gt 3000 -or $height -gt 2500) {
    throw "Actual Qt window dimensions are not usable for visual inspection"
  }
  New-Item -ItemType Directory -Force build/ci/windows11 | Out-Null
  $windowImage = [System.Drawing.Bitmap]::new($width, $height)
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($windowImage)
    try {
      $hdc = $graphics.GetHdc()
      try {
        $captured = [ANFWin32]::PrintWindow($hwnd, $hdc, [uint32]2)
        if (-not $captured) {
          $captured = [ANFWin32]::PrintWindow($hwnd, $hdc, [uint32]0)
        }
      } finally { $graphics.ReleaseHdc($hdc) }
    } finally { $graphics.Dispose() }
    if (-not $captured) { throw "External native Win32 PrintWindow failed" }
    $windowImage.Save((Join-Path (Get-Location).Path 'build/ci/windows11/native_app_window.png'),
                      [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $windowImage.Dispose() }
  Write-Host 'PASS: External Win32 PrintWindow captured actual Qt HWND after 12 UIAutomation selections.'
  # Try to make the app actually visible on the disposable desktop.
  [ANFWin32]::ShowWindow($hwnd, 9) | Out-Null
  [ANFWin32]::SetWindowPos($hwnd, [IntPtr]::new(-1), 0, 0, 1000, 700, [uint32]0x0040) | Out-Null
  [ANFWin32]::SetForegroundWindow($hwnd) | Out-Null
  Start-Sleep -Seconds 2
  $front = [ANFWin32]::GetForegroundWindow()
  Write-Host ("QtForeground={0}; ForegroundHandle={1}" -f ($front -eq $hwnd), $front)
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  if ($bounds.Width -lt 800 -or $bounds.Height -lt 600) { throw 'No usable interactive display' }
  $bitmap = [System.Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    } finally { $graphics.Dispose() }
    $bitmap.Save((Join-Path (Get-Location).Path 'build/ci/windows11/actual_desktop.png'),
                 [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $bitmap.Dispose() }
  if ($front -ne $hwnd) {
    throw 'Desktop foreground is not our app (possibly Windows 11 first-run privacy dialog). Qt screenshot exists but physical desktop UX is UNVERIFIED.'
  }
  Write-Host 'PASS: Windows 11 desktop foreground shows Qt EXE, 12 native UIA selections and native HWND screenshot.'
} finally {
  if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
}
