# Watch connector.log for IC Konsole egress POSTs
$root = Split-Path $PSScriptRoot -Parent
$log = Join-Path $root "connector.log"
$feed = Join-Path $root "ai-feed.jsonl"
$state = Join-Path $root "orchestrator-state.json"
$deadline = (Get-Date).AddMinutes(10)
$startLines = (Get-Content $log -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
Write-Host "=== IC egress monitor started $(Get-Date -Format 'HH:mm:ss') until $($deadline.ToString('HH:mm:ss')) ==="
Write-Host "Watching: konsole/analyze POST, ai-feed.jsonl, orchestrator-state.json"
Write-Host ""

while ((Get-Date) -lt $deadline) {
    $new = Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Skip $startLines
    foreach ($line in $new) {
        if ($line -match "POST /api/ui/konsole/analyze") {
            Write-Host "[HIT] $line"
        }
        if ($line -match "GET /api/ui/meta" -and $line -notmatch "dashboard") {
            Write-Host "[meta] $line"
        }
    }
    if ($new) { $startLines += $new.Count }

    $feedLines = (Get-Content $feed -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
    if ($script:lastFeedLines -and $feedLines -gt $script:lastFeedLines) {
        $last = Get-Content $feed -Tail 1
        Write-Host "[feed+] $last"
    }
    $script:lastFeedLines = $feedLines

    if (Test-Path $state) {
        $st = Get-Content $state -Raw | ConvertFrom-Json
        if ($st.last_run_at -ne $script:lastRun) {
            Write-Host "[orch] last_run=$($st.last_run_at) status=$($st.last_status) action=$($st.last_action)"
            $script:lastRun = $st.last_run_at
        }
    }

    $ic = Get-Process -Name "elbaze-desktop-tauri" -ErrorAction SilentlyContinue
    if (-not $ic -and -not $script:warnedIc) {
        Write-Host "[WARN] IC Konsole (elbaze-desktop-tauri) not running - egress POSTs will not fire"
        $script:warnedIc = $true
    }

    Start-Sleep -Seconds 15
}
Write-Host ""
Write-Host "=== Monitor ended $(Get-Date -Format 'HH:mm:ss') ==="
Select-String -Path $log -Pattern "konsole/analyze" | Select-Object -Last 3
