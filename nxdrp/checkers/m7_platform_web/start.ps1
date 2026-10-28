param(
    [int]$Port = 8000,
    [int]$Workers = 4,
    [int]$NxSlots = 1,
    [switch]$Install,
    [switch]$Build
)
$ErrorActionPreference = 'Stop'
$moduleRoot = $PSScriptRoot
$repoRoot = (Get-Item -LiteralPath $moduleRoot).Parent.Parent.Parent.FullName
$pythonExe = Join-Path $moduleRoot '.venv/Scripts/python.exe'
Push-Location -LiteralPath $repoRoot
try {
    if ($Install) {
        & python -m venv (Join-Path $moduleRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python environment setup failed' }
        & $pythonExe -m pip install -r (Join-Path $moduleRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency install failed' }
        Push-Location -LiteralPath (Join-Path $moduleRoot 'frontend')
        try {
            & npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed' }
        } finally { Pop-Location }
    }
    if ($Build -or $Install -or -not (Test-Path -LiteralPath (Join-Path $moduleRoot 'frontend/dist/index.html'))) {
        Push-Location -LiteralPath (Join-Path $moduleRoot 'frontend')
        try {
            & npm run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
        } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run start.ps1 -Install first' }
    Write-Host "M7 Web: http://127.0.0.1:$Port  | API: http://127.0.0.1:$Port/docs"
    & $pythonExe -m nxdrp.checkers.m7_platform_web --port $Port --workers $Workers --nx-slots $NxSlots
} finally { Pop-Location }
