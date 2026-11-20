@echo off
rem Arranca el editor de preguntas (independiente del juego). Se abre en el navegador.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno de Python...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)
".venv\Scripts\python.exe" src\editor.py %*
pause
exit /b 0

:error
echo.
echo No se pudo preparar el entorno. Comprueba que Python 3.11+ esta instalado.
pause
exit /b 1
