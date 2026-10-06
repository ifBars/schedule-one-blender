param(
    [string]$GamePath,
    [string]$ManagedPath,
    [string]$BlenderPath,
    [string]$OutputPath,
    [string]$PythonPath,
    [ValidateSet('extract', 'scene', 'editor')][string]$Through = 'editor',
    [switch]$Resume,
    [switch]$Doctor
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    if ($PythonPath) {
        & $PythonPath -m venv (Join-Path $PSScriptRoot '.venv')
    } else {
        & py -3.13 -m venv (Join-Path $PSScriptRoot '.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.13 with the Windows Python launcher, then retry.' }
}
& $python -c "import sys; assert sys.version_info[:2] == (3, 13), 'Python 3.13 is required'"
if ($LASTEXITCODE -ne 0) { throw 'Use a Python 3.13 environment.' }
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
$stamp = Join-Path $PSScriptRoot '.venv\requirements.sha256'
$hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
if (-not (Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $hash) {
    & $python -m pip install --requirement $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Set-Content -LiteralPath $stamp -Value $hash
}
$mode = if ($Doctor) { 'doctor' } else { 'build' }
$cliArgs = @((Join-Path $PSScriptRoot 'map.py'), $mode, '--through', $Through)
if ($GamePath) { $cliArgs += @('--game', $GamePath) }
if ($ManagedPath) { $cliArgs += @('--managed', $ManagedPath) }
if ($BlenderPath) { $cliArgs += @('--blender', $BlenderPath) }
if ($OutputPath) { $cliArgs += @('--output', $OutputPath) }
if ($Resume) { $cliArgs += '--resume' }
& $python @cliArgs
if ($LASTEXITCODE -ne 0) { throw "Map build failed with exit code $LASTEXITCODE. See the message above." }
