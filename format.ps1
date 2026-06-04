#!/usr/bin/env pwsh
# Format and lint the whole monorepo from the repository root.
# - Python (backend/): Isort, Black, Ruff using backend/.venv
# - Frontend (frontend/): ESLint + TypeScript type-check via bun
#
# Run from anywhere:  ./format.ps1

$ErrorActionPreference = "Continue"
$RepoRoot = $PSScriptRoot

Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Code Formatting & Linting" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Backend (Python)
# ---------------------------------------------------------------------------
$BackendDir = Join-Path $RepoRoot "backend"
$VenvActivate = Join-Path $BackendDir ".venv\Scripts\Activate.ps1"

if (-not (Test-Path -Path $VenvActivate)) {
    Write-Host "⚠️  Virtual environment not found at backend/.venv" -ForegroundColor Red
    exit 1
}

Write-Host "🔧 Activating virtual environment (backend/.venv)..." -ForegroundColor Yellow
& $VenvActivate
Write-Host ""

Push-Location $BackendDir

# Run Isort
Write-Host "📦 Running Isort..." -ForegroundColor Yellow
isort .
$isortExit = $LASTEXITCODE
if ($isortExit -eq 0) {
    Write-Host "✅ Isort completed successfully" -ForegroundColor Green
} else {
    Write-Host "❌ Isort failed with exit code $isortExit" -ForegroundColor Red
}
Write-Host ""

# Run Black
Write-Host "🎨 Running Black formatter..." -ForegroundColor Yellow
black .
$blackExit = $LASTEXITCODE
if ($blackExit -eq 0) {
    Write-Host "✅ Black formatting completed successfully" -ForegroundColor Green
} else {
    Write-Host "❌ Black formatting failed with exit code $blackExit" -ForegroundColor Red
}
Write-Host ""

# Run Ruff
Write-Host "🔍 Running Ruff linter with auto-fix..." -ForegroundColor Yellow
ruff check --fix .
$ruffExit = $LASTEXITCODE
if ($ruffExit -eq 0) {
    Write-Host "✅ Ruff linting completed successfully" -ForegroundColor Green
} else {
    Write-Host "⚠️  Ruff found issues (exit code $ruffExit)" -ForegroundColor Yellow
}
Write-Host ""

Pop-Location

# ---------------------------------------------------------------------------
# Frontend (TypeScript / React)
# ---------------------------------------------------------------------------
$FrontendDir = Join-Path $RepoRoot "frontend"

if (-not (Test-Path -Path $FrontendDir)) {
    Write-Host "⚠️  Frontend folder not found, skipping frontend checks" -ForegroundColor Yellow
} else {
    # bun linting
    Write-Host "📦 Running bun linting in frontend/..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    bun run lint
    $bunExit = $LASTEXITCODE
    Pop-Location
    if ($bunExit -eq 0) {
        Write-Host "✅ bun linting completed successfully" -ForegroundColor Green
    } else {
        Write-Host "⚠️  bun linting found issues (exit code $bunExit)" -ForegroundColor Yellow
    }
    Write-Host ""

    # bun tsc
    Write-Host "📦 Running bun TypeScript compilation in frontend/..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    bunx tsc --noEmit
    $tscExit = $LASTEXITCODE
    Pop-Location
    if ($tscExit -eq 0) {
        Write-Host "✅ bun TypeScript compilation completed successfully" -ForegroundColor Green
    } else {
        Write-Host "⚠️  bun TypeScript compilation found issues (exit code $tscExit)" -ForegroundColor Yellow
    }
    Write-Host ""
}

Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Formatting Complete!" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
