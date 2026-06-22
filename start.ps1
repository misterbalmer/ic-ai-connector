# IC AI Connector - start server (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Port = 8080

function Get-PortListenerPid {
    param([int]$ListenPort)
    try {
        $conn = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    } catch {
        $match = netstat -ano | Select-String "LISTENING" | Select-String ":$ListenPort\s"
        if ($match) {
            $parts = ($match.ToString().Trim() -split '\s+')
            return [int]$parts[-1]
        }
    }
    return $null
}

function Stop-StaleConnector {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    $cmd = $proc.CommandLine
    if ($cmd -match 'run\.py' -or $cmd -match [regex]::Escape($PSScriptRoot)) {
        Write-Host "Stopping existing connector on port $Port (PID $ProcessId)..."
        Stop-Process -Id $ProcessId -Force
        Start-Sleep -Seconds 1
        return $true
    }
    Write-Host "Port $Port is in use by PID $ProcessId but it does not look like IC AI Connector:"
    Write-Host "  $cmd"
    Write-Host "Stop that process manually, then run .\start.ps1 again."
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "Missing .env - copy env.example to .env and fill in your keys."
    exit 1
}

$listenerPid = Get-PortListenerPid -ListenPort $Port
if ($listenerPid) {
    Stop-StaleConnector -ProcessId $listenerPid
    $listenerPid = Get-PortListenerPid -ListenPort $Port
    if ($listenerPid) {
        Write-Host "Port $Port is still in use (PID $listenerPid). Could not free it."
        exit 1
    }
}

$python = "python"
if (Test-Path "C:\Python314\python.exe") {
    $python = "C:\Python314\python.exe"
}

& $python -m pip install -q -r requirements.txt
Write-Host "Starting IC AI Connector - dashboard at http://127.0.0.1:$Port/"
& $python run.py