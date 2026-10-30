# Run from repository root: .\scripts\preflight_public.ps1
# Read-only: does not commit/push/mutate files.
$ErrorActionPreference = 'Stop'
Write-Host "Checking Git worktree..." -ForegroundColor Cyan
& git rev-parse --show-toplevel
& git status --short
Write-Host "Checking for risky tracked files..." -ForegroundColor Cyan
$tracked = @(& git ls-files)
$risky = @($tracked | Where-Object {
    $_ -match '(^|/)(\.env(\.|$)|\.venv/|\.state/|data/|fhir-validation/|validator_cli\.jar$|.*\.sqlite3$|.*\.db$|.*\.db-wal$|.*\.db-shm$|.*\.log$|.*\.bak$)'
})
if ($risky.Count -gt 0) {
    Write-Warning "Potential secrets/private artifacts already TRACKED:"
    $risky | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Warning "Check tracked-file history and remove secrets before going Public. Gitignore alone does NOT remove history."
} else {
    Write-Host "No obvious tracked local secrets/data by filename." -ForegroundColor Green
}
$readme = Test-Path '.\README.md'
$metrics = Test-Path '.\docs\METRICS.md'
$video = Test-Path '.\docs\DEMO_VIDEO.md'
Write-Host "README.md=$readme METRICS.md=$metrics DEMO_VIDEO.md=$video"
if (-not $readme -or -not $metrics -or -not $video) { Write-Warning "Submission files missing." }
Write-Host "Now inspect README, video link, real metric values and public access manually." -ForegroundColor Yellow
