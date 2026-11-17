# Atajo para Windows PowerShell:  .\scripts\up.ps1 [demo|dev]
# Requiere Git Bash (viene con Git para Windows).
$ErrorActionPreference = "Stop"
bash "$PSScriptRoot/up.sh" @args
exit $LASTEXITCODE
