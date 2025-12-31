@echo off
start "KnowWhere - Burst Stop" cmd /k "powershell -ExecutionPolicy Bypass -File "%~dp0burst-stop.ps1""
