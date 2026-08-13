$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    Write-Error 'Python 3.11 or 3.12 is required.'
    exit 1
}

& $Python.Source (Join-Path $PSScriptRoot 'manage.py') @args
exit $LASTEXITCODE
