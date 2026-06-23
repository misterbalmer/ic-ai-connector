# IC AI Connector - stop server (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Port = 8080

try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
        Select-Object -First 1
    $processId = [int]$conn.OwningProcess
} catch {
    $match = netstat -ano | Select-String "LISTENING" | Select-String ":$Port\s"
    if (-not $match) {
        Write-Host "No process listening on port $Port."
        exit 0
    }
    $parts = ($match.ToString().Trim() -split '\s+')
    $processId = [int]$parts[-1]
}

$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "Stopping PID ${processId}: $($proc.CommandLine)"
}
Stop-Process -Id $processId -Force
Write-Host "Connector stopped."