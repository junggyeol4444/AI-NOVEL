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
  $expand = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    '세부 도구 보기')
  $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                            $expand)
  if ($buttons.Count -eq 0) {
    # Depending on the Qt UIAutomation bridge, objectName can surface as
    # AutomationId instead of an accessible Name.
    $idCondition = [System.Windows.Automation.PropertyCondition]::new(
      [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
      'showAdvancedNavigationButton')
    $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                             $idCondition)
  }
  Write-Host ('AdvancedMenuButtonCandidates=' + $buttons.Count)
  $expanded = $false
  foreach ($button in $buttons) {
    # Qt checkable QPushButton can surface as ControlType.CheckBox rather than
    # ControlType.Button. Match by the exact accessible name/AutomationId above
    # and inspect supported patterns instead of filtering by ControlType.
    Write-Host ('AdvancedMenuControlType=' + $button.Current.ControlType.ProgrammaticName)
    # Checkable QPushButton on Windows may support TogglePattern but NOT
    # InvokePattern. Never assume a checkable toggle is an ordinary button.
    $toggle = $null
    if ($button.TryGetCurrentPattern(
         [System.Windows.Automation.TogglePattern]::Pattern, [ref]$toggle)) {
      $p = [System.Windows.Automation.TogglePattern]$toggle
      if ($p.Current.ToggleState -ne
          [System.Windows.Automation.ToggleState]::On) { $p.Toggle() }
      $expanded = $true
      break
    }
    $pattern = $null
    if ($button.TryGetCurrentPattern(
         [System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
      ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
      $expanded = $true
      break
    }
  }
  if (-not $expanded) {
    throw 'Windows UIAutomation cannot expand the advanced twelve-tool menu'
  }
  Start-Sleep -Milliseconds 350
  $wanted = @('작품 홈', '작품 설정', '등장인물', '세계관', '시간선', '인물 관계', '복선 관리', '참고소설', '참고 패턴', '회차 기획', '유사성 검사', '내보내기·출판')
  # QListWidget exposes only the currently visible rows to some Qt UIA
  # bridges. A single FindAll snapshot cannot cover twelve scrollable rows.
  # Scroll the actual sidebar through OS UIAutomation and re-enumerate.
  $sidebarCondition = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
    'sectionSidebar')
  $sidebar = $root.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants, $sidebarCondition)
  if ($null -eq $sidebar) {
    $listCondition = [System.Windows.Automation.PropertyCondition]::new(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::List)
    $lists = $root.FindAll(
      [System.Windows.Automation.TreeScope]::Descendants, $listCondition)
    foreach ($candidate in $lists) {
      $children = $candidate.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
      foreach ($child in $children) {
        if ($wanted -contains $child.Current.Name) {
          $sidebar = $candidate
          break
        }
      }
      if ($null -ne $sidebar) { break }
    }
  }
  Write-Host ('NativeSidebarFound=' + ($null -ne $sidebar))
  $scrollPattern = $null
  if ($null -ne $sidebar) {
    $scrollCandidates = $sidebar.FindAll(
      [System.Windows.Automation.TreeScope]::Subtree,
      [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($candidate in $scrollCandidates) {
      $possible = $null
      if ($candidate.TryGetCurrentPattern(
          [System.Windows.Automation.ScrollPattern]::Pattern, [ref]$possible)) {
        $p = [System.Windows.Automation.ScrollPattern]$possible
        if ($p.Current.VerticallyScrollable) {
          $scrollPattern = $p
          break
        }
      }
    }
  }
  Write-Host ('NativeSidebarScrollAvailable=' + ($null -ne $scrollPattern))
  # Qt QListWidget on Windows may expose a vertical scrollbar with
  # RangeValuePattern but no ScrollPattern on the list itself.
  $rangeScroll = $null
  if ($null -eq $scrollPattern -and $null -ne $sidebar) {
    $barCondition = [System.Windows.Automation.PropertyCondition]::new(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::ScrollBar)
    $bars = $sidebar.FindAll(
      [System.Windows.Automation.TreeScope]::Descendants, $barCondition)
    if ($bars.Count -eq 0) {
      # Some Qt UIA providers expose scrollbars as siblings of the list.
      # Only accept a scrollbar geometrically inside the named sidebar.
      $bars = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants, $barCondition)
    }
    Write-Host ('NativeSidebarScrollBarCandidates=' + $bars.Count)
    $sideBounds = $sidebar.Current.BoundingRectangle
    foreach ($bar in $bars) {
      $barBounds = $bar.Current.BoundingRectangle
      if ($barBounds.Left -lt ($sideBounds.Left - 5) -or
          $barBounds.Right -gt ($sideBounds.Right + 5) -or
          $barBounds.Top -lt ($sideBounds.Top - 5) -or
          $barBounds.Bottom -gt ($sideBounds.Bottom + 5)) { continue }
      if ($barBounds.Width -gt 0 -and $barBounds.Height -gt 0 -and
          $barBounds.Height -le $barBounds.Width) { continue }
      $possibleRange = $null
      if ($bar.TryGetCurrentPattern(
          [System.Windows.Automation.RangeValuePattern]::Pattern,
          [ref]$possibleRange)) {
        $candidateRange = [System.Windows.Automation.RangeValuePattern]$possibleRange
        if (-not $candidateRange.Current.IsReadOnly -and
            $candidateRange.Current.Maximum -gt $candidateRange.Current.Minimum) {
          $rangeScroll = $candidateRange
          break
        }
      }
    }
  }
  Write-Host ('NativeSidebarRangeScrollAvailable=' + ($null -ne $rangeScroll))
  $selected = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal)
  $clicks = 0
  $allCount = 0
  for ($pass = 0; $pass -lt 16; $pass++) {
    $all = $root.FindAll(
      [System.Windows.Automation.TreeScope]::Descendants,
      [System.Windows.Automation.Condition]::TrueCondition)
    $allCount = $all.Count
    foreach ($entry in $all) {
      $name = $entry.Current.Name
      if (-not $name -or $wanted -notcontains $name -or $selected.Contains($name)) {
        continue
      }
      $pattern = $null
      if ($entry.TryGetCurrentPattern(
          [System.Windows.Automation.SelectionItemPattern]::Pattern,
          [ref]$pattern)) {
        ([System.Windows.Automation.SelectionItemPattern]$pattern).Select()
        [void]$selected.Add($name)
        $clicks++
        Start-Sleep -Milliseconds 125
      }
    }
    Write-Host ("NativeSidebarPass={0}; SelectedUnique={1}" -f $pass, $selected.Count)
    if ($selected.Count -ge $wanted.Count) { break }
    if ($null -eq $scrollPattern -and $null -eq $rangeScroll) { break }
    if ($null -ne $scrollPattern) {
      $before = $scrollPattern.Current.VerticalScrollPercent
      if ($before -ge 99.9) { break }
      $scrollPattern.Scroll(
        [System.Windows.Automation.ScrollAmount]::NoAmount,
        [System.Windows.Automation.ScrollAmount]::LargeIncrement)
      Start-Sleep -Milliseconds 250
      $after = $scrollPattern.Current.VerticalScrollPercent
    } else {
      $before = [double]$rangeScroll.Current.Value
      $step = [Math]::Max([double]1, [double]$rangeScroll.Current.LargeChange)
      $target = [Math]::Min(
        [double]$rangeScroll.Current.Maximum, [double]($before + $step))
      if ($target -le $before) { break }
      $rangeScroll.SetValue($target)
      Start-Sleep -Milliseconds 250
      $after = [double]$rangeScroll.Current.Value
    }
    Write-Host ("NativeSidebarScrollPosition={0}->{1}" -f $before, $after)
    if ($after -le $before) { break }
  }
  Write-Host ("AutomationElements={0}; MatchedMenuItems={1}; NativeSelectionClicks={2}" -f $allCount, $selected.Count, $clicks)
  if ($clicks -lt 12) {
    throw "Windows UIAutomation failed to select all twelve visible sidebar pages; this is NOT a passing GUI review"
  }
  # Merely highlighting the 'Publication' sidebar item is insufficient: the
  # stacked content page must really switch, exposing its action controls.
  $after = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                         [System.Windows.Automation.Condition]::TrueCondition)
  $publicationActions = 0
  foreach ($element in $after) {
    $label = $element.Current.Name
    if ($label -and ($label -like '*TXT + EPUB 비공개 내보내기*' -or
                     $label -like '*WordPress 비공개 초안 전송*')) {
      $publicationActions++
    }
  }
  Write-Host ("PublicationPageActionsVisibleViaUIA=" + $publicationActions)
  if ($publicationActions -lt 1) {
    throw "UI Automation selected Publication sidebar row but the actual publication page did not open"
  }
  # Inspect the actual entry screen, not only the legacy publishing form.
  # Select the first localized sidebar item through native Windows UIA.
  $homeName = [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::NameProperty, '작품 홈')
  $homeCandidates = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                                  $homeName)
  $homeSelected = $false
  foreach ($candidate in $homeCandidates) {
    $selectionPattern = $null
    if ($candidate.Current.ControlType.ProgrammaticName -like '*ListItem' -and
        $candidate.TryGetCurrentPattern(
          [System.Windows.Automation.SelectionItemPattern]::Pattern,
          [ref]$selectionPattern)) {
      ([System.Windows.Automation.SelectionItemPattern]$selectionPattern).Select()
      $homeSelected = $true
      break
    }
  }
  if (-not $homeSelected) { throw 'Native UIAutomation did not select project home' }
  Start-Sleep -Milliseconds 300
  Write-Host 'PASS: External Windows UIAutomation returned to user-facing project home for screenshot.'
  # Default user experience hides specialist tools; return the advanced
  # drawer to its default collapsed state before taking the desktop capture.
  $collapseButtons = $root.FindAll(
      [System.Windows.Automation.TreeScope]::Descendants, $expand)
  if ($collapseButtons.Count -eq 0) {
    $idCondition = [System.Windows.Automation.PropertyCondition]::new(
      [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
      'showAdvancedNavigationButton')
    $collapseButtons = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants, $idCondition)
  }
  $collapsed = $false
  foreach ($button in $collapseButtons) {
    # The same Qt checkable control may be a CheckBox on Windows UIA.
    Write-Host ('AdvancedMenuCollapseControlType=' + $button.Current.ControlType.ProgrammaticName)
    $toggle = $null
    if ($button.TryGetCurrentPattern(
        [System.Windows.Automation.TogglePattern]::Pattern, [ref]$toggle)) {
      $p = [System.Windows.Automation.TogglePattern]$toggle
      if ($p.Current.ToggleState -ne
          [System.Windows.Automation.ToggleState]::Off) { $p.Toggle() }
      $collapsed = $true
      break
    }
    $pattern = $null
    if ($button.TryGetCurrentPattern(
          [System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
      ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
      $collapsed = $true
      break
    }
  }
  if (-not $collapsed) { throw 'Could not restore collapsed user-facing navigation' }
  Start-Sleep -Milliseconds 250
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
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
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
  $foregroundRequestAccepted = [ANFWin32]::SetForegroundWindow($hwnd)
  Write-Host ("ForegroundRequestAccepted={0}" -f $foregroundRequestAccepted)
  Start-Sleep -Seconds 2
  $front = [ANFWin32]::GetForegroundWindow()
  Write-Host ("QtForeground={0}; ForegroundHandle={1}" -f ($front -eq $hwnd), $front)
  if ($front -ne $hwnd -and $front -ne [IntPtr]::Zero) {
    # Diagnostics only: do not dismiss, kill, or bypass OS foreground UI.
    $frontPid = [uint32]0
    [ANFWin32]::GetWindowThreadProcessId($front, [ref]$frontPid) | Out-Null
    $frontProcess = Get-Process -Id $frontPid -ErrorAction SilentlyContinue
    $frontName = if ($frontProcess) { $frontProcess.ProcessName } else { 'unavailable' }
    Write-Host ("ForegroundBlockerProcess={0}; ForegroundBlockerPid={1}" -f $frontName, $frontPid)
  }
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
