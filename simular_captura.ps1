# Wrapper PowerShell para simular_captura.bat dentro de VS Code
param([string]$Accion = "", [string]$Extra = "")
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "simular_captura.bat"
& cmd.exe /c "`"$script`" $Accion $Extra"
