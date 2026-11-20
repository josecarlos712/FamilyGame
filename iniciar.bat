@echo off
rem Arranca FamilyGame. La primera vez crea el entorno e instala lo necesario.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno de Python...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)
rem Abre la pantalla de la tele cuando el servidor ya esta escuchando
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8765/tv"
".venv\Scripts\python.exe" src\main.py %*
pause
exit /b 0

:error
echo.
echo No se pudo preparar el entorno. Comprueba que Python 3.11+ esta instalado.
pause
exit /b 1
