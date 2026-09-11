@echo off
setlocal

rem Run from the project directory even when this launcher is double-clicked
rem or invoked from another working directory.
pushd "%~dp0" || (
    echo ERROR: Could not open the VertiSea project directory.
    pause
    exit /b 1
)

rem Prefer a working project virtual environment, then fall back to a system Python.
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

where py >nul 2>&1
if not errorlevel 1 goto run_py

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    goto run_python
)

echo ERROR: Python 3 was not found.
echo Create the project virtual environment or install Python 3.
popd
pause
exit /b 1

:run_py
py -3 "%~dp0current_filter_test.py" %*
goto finished

:run_python
"%PYTHON_EXE%" "%~dp0current_filter_test.py" %*

:finished
set "EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EXIT_CODE%"=="0" (
    echo.
    echo current_filter_test.py exited with error code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%