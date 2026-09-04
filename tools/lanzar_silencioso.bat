@echo off
REM No se abre con doble clic - lo llama AutoCAD-IA.vbs, que lo corre oculto.
REM Toda la salida va al log, ya no hay pantalla donde mostrarla.
cd /d "%~dp0\.."
set "PYW=mcp_server\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
REM Sin esto, Python guarda la salida en un buffer y no la escribe en el
REM log hasta que se llena o el proceso termina - el log se veia vacio
REM aunque el servidor ya llevara rato corriendo.
set "PYTHONUNBUFFERED=1"
"%PYW%" iniciar.py >> autocad-ia.log 2>&1
