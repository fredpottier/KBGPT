@echo off
start "KnowWhere - Build App" cmd /k "powershell -ExecutionPolicy Bypass -File "%~dp0build-app.ps1""
