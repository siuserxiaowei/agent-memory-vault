$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
python (Join-Path $PSScriptRoot 'test_skill.py')
exit $LASTEXITCODE
