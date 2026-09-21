# Обёртка healthcheck для Windows PowerShell.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python (Join-Path $ScriptDir "healthcheck.py") @args

