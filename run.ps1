#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Start or stop the Translatio containers.

.EXAMPLE
    ./run.ps1 start          # development: hot reload, http://localhost:3000
    ./run.ps1 start -Prod    # production images (nginx frontend, no reload)
    ./run.ps1 stop           # stop and remove the containers (data/ is kept)
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("start", "stop")]
    [string]$Action,

    [switch]$Prod
)

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is not running: start Docker Desktop and try again."
    }

    $compose = @("compose", "-f", "docker-compose.yml")
    if (-not $Prod) { $compose += @("-f", "docker-compose.dev.yml") }
    $mode = if ($Prod) { "production" } else { "development" }

    if ($Action -eq "start") {
        if (-not (Test-Path ".env")) {
            throw "Missing .env in the repo root (copy .env.example and add your API keys)."
        }
        Write-Host "Starting ($mode)..." -ForegroundColor Cyan
        & docker @compose up --build -d
        if ($LASTEXITCODE -ne 0) { throw "docker compose up failed." }

        # Wait until both services answer (the dev frontend installs packages first)
        Write-Host "Waiting for the services..." -ForegroundColor DarkGray
        $ready = $false
        foreach ($i in 1..90) {
            try {
                Invoke-WebRequest "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
                Invoke-WebRequest "http://localhost:3000" -UseBasicParsing -TimeoutSec 2 | Out-Null
                $ready = $true
                break
            }
            catch { Start-Sleep -Seconds 2 }
        }
        if (-not $ready) {
            Write-Host "Services are not answering yet: check the logs." -ForegroundColor Yellow
        }
        Write-Host "Frontend: http://localhost:3000" -ForegroundColor Green
        Write-Host "Backend:  http://localhost:8000" -ForegroundColor Green
        Write-Host "Logs:     docker $($compose -join ' ') logs -f" -ForegroundColor DarkGray
    }
    else {
        Write-Host "Stopping ($mode)..." -ForegroundColor Cyan
        & docker @compose down
        if ($LASTEXITCODE -ne 0) { throw "docker compose down failed." }
    }
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
