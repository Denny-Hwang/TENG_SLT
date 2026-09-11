@echo off
setlocal

rem Run from the project directory even when this launcher is double-clicked
rem or invoked from another working directory.
pushd "%~dp0" || (
    echo ERROR: Could not open the VertiSea project directory.
    pause
    exit /b 1
)

rem Prefer a working project environment, then fall back to a system Python.
rem
rem TWO layouts are checked because they differ, and checking only the first one meant a
rem conda environment created in the project folder was silently ignored and the launcher
rem fell through to whatever Python happened to be on PATH:
rem     venv / virtualenv -> .venv\Scripts\python.exe
rem     conda -p .\.venv  -> .venv\python.exe        (conda puts python.exe at the root)
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
        goto run_python
    )
    if exist "%~dp0.venv\Lib\site-packages" (
        set "PYTHONPATH=%~dp0.venv\Lib\site-packages;%PYTHONPATH%"
    )
)

if exist "%~dp0.venv\python.exe" (
    "%~dp0.venv\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%~dp0.venv\python.exe"
        goto run_python
    )
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import serial, matplotlib, tkinter" >nul 2>&1
    if not errorlevel 1 goto run_py
)

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import serial, matplotlib, tkinter" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        goto run_python
    )
)

echo ERROR: A Python 3 installation with pyserial, matplotlib, and tkinter was not found.
echo Repair the project virtual environment or install the missing dependencies.
popd
pause
exit /b 1

:run_py
py -3 "%~dp0vertisea_plot_v7.py" %*
goto finished

:run_python
"%PYTHON_EXE%" "%~dp0vertisea_plot_v7.py" %*

:finished
set "EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EXIT_CODE%"=="0" (
    echo.
    echo vertisea_plot_v7.py exited with error code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%