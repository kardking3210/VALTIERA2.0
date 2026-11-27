$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

foreach ($command in @('node', 'npm', 'docker')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command '$command' was not found. Install Node.js and Docker Desktop, then retry."
    }
}
try { docker info *> $null } catch { throw 'Docker Desktop must be running before local startup.' }

if (-not (Test-Path (Join-Path $repo 'node_modules'))) { npm install }
docker compose up -d --build

$apiReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3
        if ($health.database -eq 'OPERATIONAL') { $apiReady = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $apiReady) { throw 'The API did not become healthy. Run docker compose logs api migrate postgres to inspect startup.' }

$frontend = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
if (-not $frontend) {
    Start-Process -FilePath 'npm.cmd' -ArgumentList @('run','dev','--','--host','127.0.0.1') -WorkingDirectory $repo -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { $null = Invoke-WebRequest 'http://127.0.0.1:5173' -TimeoutSec 2 -UseBasicParsing; break }
        catch { Start-Sleep -Seconds 1 }
    }
}

$demo = Invoke-RestMethod 'http://127.0.0.1:8000/demo-users'
Write-Host 'VALTIERA local stack is ready.'
Write-Host 'Frontend: http://127.0.0.1:5173'
Write-Host 'Backend:  http://127.0.0.1:8000'
Write-Host 'API docs: http://127.0.0.1:8000/docs'
Write-Host "Database: $($health.database) · Worker: $($health.worker) · Demo profiles: $($demo.users.Count)"
