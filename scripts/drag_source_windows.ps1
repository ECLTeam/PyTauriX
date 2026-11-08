# PyTauriX
# 文件作用：为真实 OLE 拖放验收创建独立文件源窗口，不操作 Explorer 或用户文件。
param([Parameter(Mandatory=$true)][string]$Path, [Parameter(Mandatory=$true)][string]$Title)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = [System.Windows.Forms.Form]::new()
$form.Text = $Title
$form.StartPosition = "Manual"
$form.Location = [System.Drawing.Point]::new(30, 120)
$form.Size = [System.Drawing.Size]::new(300, 180)
$form.TopMost = $true
[Console]::WriteLine("OLE_SOURCE_READY " + $PID + " " + $form.Text)
$label = [System.Windows.Forms.Label]::new()
$label.Text = "PyTauriX owned OLE source"
$label.Dock = "Fill"
$label.TextAlign = "MiddleCenter"
$form.Controls.Add($label)
$label.Add_MouseDown({
    if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $data = [System.Windows.Forms.DataObject]::new()
        $files = [System.Collections.Specialized.StringCollection]::new()
        [void]$files.Add($Path)
        $data.SetFileDropList($files)
        $effect = $label.DoDragDrop($data, [System.Windows.Forms.DragDropEffects]::Copy)
        [Console]::WriteLine("OLE_SOURCE_RESULT " + $effect)
    }
})
$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 25000
$timer.Add_Tick({ $form.Close() })
$timer.Start()
try { [System.Windows.Forms.Application]::Run($form) }
finally { $timer.Dispose(); $form.Dispose() }
