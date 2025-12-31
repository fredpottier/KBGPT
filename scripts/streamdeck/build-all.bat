@echo off
start "KnowWhere - Build All" cmd /k "powershell -ExecutionPolicy Bypass -File "%~dp0build-all.ps1""
