# One-time IC Konsole -> AIConnector egress setup
# Writes connector.env (no admin). Hosts edit auto-requests UAC when needed.

param(
    [switch]$HostsOnly
)

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-HostsHasIcSnapshot {
    param([string]$HostsPath)
    $text = Get-Content $HostsPath -Raw -ErrorAction SilentlyContinue
    return ($text -match "(?m)^\s*127\.0\.0\.1\s+ic\.snapshot\s*$")
}

function Add-IcSnapshotHostsEntry {
    param([string]$HostsPath, [string]$Entry)
    if (Test-HostsHasIcSnapshot -HostsPath $HostsPath) {
        Write-Host "[OK] hosts already contains: $Entry"
        return $true
    }
    if (-not (Test-IsAdmin)) {
        return $false
    }
    Add-Content -Path $HostsPath -Value "`n$Entry"
    Write-Host "[OK] Added to hosts: $Entry"
    return $true
}

$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$entry = "127.0.0.1 ic.snapshot"
$connectorDir = Join-Path $env:APPDATA "InstitutionalCharts"
$connectorEnv = Join-Path $connectorDir "connector.env"
$sourceEnv = Resolve-Path (Join-Path $PSScriptRoot "..\.env")

Write-Host "IC Konsole egress setup"
Write-Host ""

if ($HostsOnly) {
    if (-not (Test-IsAdmin)) {
        Write-Host "[FAIL] Hosts edit still requires Administrator."
        exit 1
    }
    if (Add-IcSnapshotHostsEntry -HostsPath $hostsPath -Entry $entry) {
        exit 0
    }
    exit 1
}

# --- connector.env (no admin required) ---
$tokenLine = Select-String -Path $sourceEnv -Pattern "^CONNECTOR_TOKEN=" | Select-Object -First 1
if (-not $tokenLine) {
    Write-Host "[FAIL] CONNECTOR_TOKEN not found in $sourceEnv"
    exit 1
}

New-Item -ItemType Directory -Force -Path $connectorDir | Out-Null
$tokenLine.Line | Set-Content -Path $connectorEnv -Encoding UTF8
Write-Host "[OK] Wrote $connectorEnv"

# --- hosts (admin required) ---
if (Test-HostsHasIcSnapshot -HostsPath $hostsPath) {
    Write-Host "[OK] hosts already contains: $entry"
} elseif (Test-IsAdmin) {
    Add-IcSnapshotHostsEntry -HostsPath $hostsPath -Entry $entry | Out-Null
} else {
    Write-Host "[..] Hosts entry missing. Accept the UAC prompt to add: $entry"
    $elevArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -HostsOnly"
    try {
        $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $elevArgs -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            throw "Elevated hosts step failed (exit $($proc.ExitCode))"
        }
    } catch {
        Write-Host ""
        Write-Host "[FAIL] Could not update hosts automatically."
        Write-Host "  1. Right-click PowerShell -> Run as administrator"
        Write-Host "  2. Run:  cd `"$PSScriptRoot`""
        Write-Host "         .\setup-ic-egress.ps1 -HostsOnly"
        Write-Host "  Or edit manually (Notepad as admin): $hostsPath"
        Write-Host "  Add this line:  $entry"
        exit 1
    }
    if (-not (Test-HostsHasIcSnapshot -HostsPath $hostsPath)) {
        Write-Host "[FAIL] hosts still missing ic.snapshot after elevated run."
        exit 1
    }
}

# --- verify ---
try {
    $meta = Invoke-WebRequest -Uri "http://ic.snapshot:8080/api/ui/meta" -UseBasicParsing -TimeoutSec 5
    Write-Host "[OK] Meta probe: $($meta.StatusCode) $($meta.Content)"
} catch {
    Write-Host "[WARN] ic.snapshot:8080 not reachable. Start AIConnector first (start.ps1), then restart IC Konsole."
}

Write-Host ""
Write-Host "Next: restart IC Konsole so the startup meta probe runs with connector up."
