@echo off
start "KnowWhere - Build Infra" cmd /k "powershell -ExecutionPolicy Bypass -File "%~dp0build-infra.ps1""
