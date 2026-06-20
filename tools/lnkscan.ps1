$ErrorActionPreference = 'SilentlyContinue'
$sh = New-Object -ComObject WScript.Shell
$roots = @(
    [Environment]::GetFolderPath('Desktop'),
    "$env:APPDATA\Microsoft\Windows\Start Menu",
    "$env:ProgramData\Microsoft\Windows\Start Menu",
    "$env:APPDATA\Microsoft\Internet Explorer\Quick Launch"
)
Write-Output '=== Chrome shortcuts carrying --remote-debugging-port ==='
$found = $false
foreach ($r in $roots) {
    Get-ChildItem -Path $r -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        $lnk = $sh.CreateShortcut($_.FullName)
        if ($lnk.TargetPath -match 'chrome\.exe' -and $lnk.Arguments -match 'remote-debugging-port') {
            $found = $true
            "FILE: $($_.FullName)"
            "  ARGS: $($lnk.Arguments)"
        }
    }
}
if (-not $found) { 'none found in shortcut folders' }

Write-Output '=== Run / RunOnce registry autostarts mentioning the flag ==='
foreach ($k in 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Run') {
    $p = Get-ItemProperty $k
    if ($p) {
        $p.PSObject.Properties | Where-Object { $_.Value -match 'remote-debugging-port' } | ForEach-Object {
            "$k :: $($_.Name) = $($_.Value)"
        }
    }
}
