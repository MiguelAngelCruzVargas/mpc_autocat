@echo off
REM Doble clic para abrir la interfaz de AutoCAD IA.
REM Se queda abierto: esta ventana ES el servidor. Cerrarla apaga la app.
cd /d "%~dp0"
title AutoCAD IA
echo.
echo   Iniciando AutoCAD IA...
echo.
if exist "mcp_server\.venv\Scripts\python.exe" (
    "mcp_server\.venv\Scripts\python.exe" iniciar.py
) else (
    python iniciar.py
)
if errorlevel 1 (
    echo.
    echo   Hubo un problema al iniciar. Revisa el mensaje de arriba.
    pause
)
