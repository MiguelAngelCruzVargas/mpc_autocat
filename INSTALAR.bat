@echo off
REM Doble clic para instalar AutoCAD IA en esta computadora (no pide administrador).
REM Hace lo mismo que:  powershell -File tools\instalar.ps1
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\instalar.ps1" %*
echo.
pause
