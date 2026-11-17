# Atajo para Windows PowerShell:  .\scripts\down.ps1 [recursos]
$ErrorActionPreference = "Stop"
bash "$PSScriptRoot/down.sh" @args
exit $LASTEXITCODE
