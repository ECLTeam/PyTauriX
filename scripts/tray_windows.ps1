# PyTauriX
# 文件作用：只读取 Windows 通知区域中自有测试图标或溢出按钮的 UI Automation 数据。
param([string]$Tooltip, [switch]$Chevron, [switch]$Inspect)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class TrayInspection {
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", EntryPoint="FindWindowW", CharSet=CharSet.Unicode)]
    public static extern IntPtr FindWindow(string className, string title);
}
"@
$automation = [System.Windows.Automation.AutomationElement]
$scope = [System.Windows.Automation.TreeScope]
$taskbarHandle = [TrayInspection]::FindWindow("Shell_TrayWnd", $null)
if ($taskbarHandle -eq [IntPtr]::Zero) { throw "Windows taskbar unavailable" }
# 自动隐藏期间任务栏可能暂时退出 UIA 根节点列表，原生句柄仍然有效。
$taskbar = $automation::FromHandle($taskbarHandle)
$processCondition = [System.Windows.Automation.PropertyCondition]::new($automation::ProcessIdProperty, $taskbar.Current.ProcessId)
$roots = @($taskbar) + @($automation::RootElement.FindAll($scope::Children, $processCondition) | Where-Object {
    $_.Current.NativeWindowHandle -ne $taskbarHandle.ToInt64() -and [TrayInspection]::IsWindowVisible([IntPtr]$_.Current.NativeWindowHandle)
})
if ($Inspect) {
    foreach ($rootElement in $roots) {
        $rootElement.FindAll($scope::Descendants, [System.Windows.Automation.Condition]::TrueCondition) | Where-Object { $_.Current.Name.StartsWith($Tooltip) } | ForEach-Object {
            [pscustomobject]@{ name = $_.Current.Name; class = $_.Current.ClassName; offscreen = $_.Current.IsOffscreen; root = $rootElement.Current.ClassName; bounds = $_.Current.BoundingRectangle.ToString(); rootBounds = $rootElement.Current.BoundingRectangle.ToString() } | ConvertTo-Json -Compress
        }
    }
    exit 0
}
$names = if ($Chevron) { @("显示隐藏的图标", "Show hidden icons") } else { @($Tooltip) }
foreach ($rootElement in $roots) {
    foreach ($targetName in $names) {
        $iconCondition = [System.Windows.Automation.PropertyCondition]::new($automation::ClassNameProperty, "SystemTray.NormalButton")
        # Explorer 更新提示后会把初始显示名和当前提示拼接为 Name，保留两者验证当前提示。
        $elements = $rootElement.FindAll($scope::Descendants, $iconCondition) | Where-Object { $_.Current.Name -eq $targetName -or $_.Current.Name.EndsWith(" " + $targetName) }
        foreach ($element in $elements) {
            $current = $element.Current
            $bounds = $current.BoundingRectangle
            if (-not $current.IsOffscreen -and $bounds.Width -gt 0 -and $bounds.Height -gt 0) {
                $expanded = @($roots | Where-Object { $_.Current.ClassName -match "Overflow" -and -not $_.Current.IsOffscreen -and $_.Current.BoundingRectangle.Width -gt 0 -and $_.Current.BoundingRectangle.Height -gt 0 }).Count -gt 0
                [pscustomobject]@{ name = $current.Name; x = $bounds.X; y = $bounds.Y; width = $bounds.Width; height = $bounds.Height; expanded = $expanded } | ConvertTo-Json -Compress
                exit 0
            }
        }
    }
}
Write-Output "null"
