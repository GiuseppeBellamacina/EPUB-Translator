#!/usr/bin/env pwsh
# Format and lint the whole monorepo inside the dev containers (only Docker is needed on the host).
# - Python (backend/): isort, black, ruff
# - Frontend (frontend/): ESLint + TypeScript type-check via bun
#
# Run from anywhere:  ./format.ps1

$ErrorActionPreference = "Continue"
Push-Location $PSScriptRoot

$Compose = @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")
$results = [ordered]@{}

function Invoke-Step($name, [string[]]$cmd) {
    Write-Host "🔧 $name..." -ForegroundColor Yellow
    & docker @Compose run --rm --no-deps @cmd
    $results[$name] = $LASTEXITCODE
    Write-Host ""
}

Invoke-Step "isort" @("backend", "isort", ".")
Invoke-Step "black" @("backend", "black", ".")
Invoke-Step "ruff" @("backend", "ruff", "check", "--fix", ".")
Invoke-Step "eslint" @("frontend", "sh", "-c", "bun install --frozen-lockfile && bun run lint")
Invoke-Step "tsc" @("frontend", "sh", "-c", "bun install --frozen-lockfile && bunx tsc -b --noEmit")

Pop-Location

Write-Host "================================" -ForegroundColor Cyan
foreach ($step in $results.Keys) {
    if ($results[$step] -eq 0) {
        Write-Host "✅ $step" -ForegroundColor Green
    } else {
        Write-Host "❌ $step (exit code $($results[$step]))" -ForegroundColor Red
    }
}
Write-Host "================================" -ForegroundColor Cyan
