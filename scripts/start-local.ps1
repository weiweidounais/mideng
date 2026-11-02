param([int]$Port = 8000, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    $uvPath = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe'
    if (Test-Path -LiteralPath $uvPath) { $uvCommand = Get-Item -LiteralPath $uvPath }
}
if (-not $npmCommand -or -not $uvCommand) { throw 'Install Node.js (with npm), Python 3.12 and uv first; then reopen the terminal.' }
$uvExecutable = if ($uvCommand.Source) { $uvCommand.Source } else { $uvCommand.FullName }
if (-not $SkipBuild) {
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) {
            & $npmCommand.Source ci --ignore-scripts --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
            & node node_modules/esbuild/install.js
            if ($LASTEXITCODE -ne 0) { throw 'esbuild setup failed' }
        }
        & $npmCommand.Source run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
Push-Location (Join-Path $projectRoot 'backend')
try {
    & $uvExecutable sync --frozen --python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency setup failed' }
    $env:PYTHONUTF8 = '1'
    $env:LANGSMITH_TRACING = 'false'
    Write-Output "Mideng: http://127.0.0.1:$Port"
    Write-Output 'First-start passwords: DATA_DIR/bootstrap-passwords.json (default backend/.runtime). Keep this file private.'
    & $uvExecutable run --no-sync uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally { Pop-Location }
