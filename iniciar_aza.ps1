# Wrapper PowerShell para iniciar_aza.bat dentro de VS Code
param([string]$Modo = "", [string]$Extra = "")
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "iniciar_aza.bat"
& cmd.exe /c "`"$script`" $Modo $Extra"
