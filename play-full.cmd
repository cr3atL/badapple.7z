@echo off
setlocal
"%SystemRoot%\System32\conhost.exe" "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\play.ps1" -Preset full
