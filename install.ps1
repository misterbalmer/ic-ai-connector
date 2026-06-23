# IC AI Connector — one-time install (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    $candidates = @(
        "C:\Python314\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "[FAIL] Python 3.11+ not found."
    Write-Host "       Install from https://www.python.org/downloads/ (check 'Add to PATH')."
    exit 1
}

$version = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$majorMinor = $version.Split(".")
if ([int]$majorMinor[0] -lt 3 -or ([int]$majorMinor[0] -eq 3 -and [int]$majorMinor[1] -lt 11)) {
    Write-Host "[FAIL] Python 3.11+ required (found $version)"
    exit 1
}
Write-Host "[OK] Python $version"

if (-not (Test-Path ".venv")) {
    Write-Host "[..] Creating virtual environment..."
    & $python -m venv .venv
}
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r requirements.txt -q
Write-Host "[OK] Dependencies installed"

& $venvPython scripts/setup_wizard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $venvPython scripts/doctor.py --binance
exit $LASTEXITCODE