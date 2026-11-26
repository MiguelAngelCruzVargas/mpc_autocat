@echo off
REM Doble clic: conecta Vigentra Architech con tu suscripcion de Claude o ChatGPT
REM (Claude de escritorio, Claude Code, Codex u OpenCode, los que tengas instalados).
REM No pide administrador. Ver GUIA_SUSCRIPCION.txt
chcp 65001 >nul
title Conectar mi suscripción con Vigentra Architech
echo.
echo  Conectando Vigentra Architech con tu suscripción de IA...
echo.
set "PY=%~dp0mcp_server\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0tools\registrar_clientes.py" --amigable --python "%PY%" --server "%~dp0mcp_server\server.py"
echo.
pause
