@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

rem Prefer the runtime bundled in a release archive.
if exist "runtime\python.exe" set "ZY_PYTHON=runtime\python.exe"& goto run
if exist ".venv\Scripts\python.exe" set "ZY_PYTHON=.venv\Scripts\python.exe"& goto run
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "ZY_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"& goto run
where py >nul 2>nul
if not errorlevel 1 set "ZY_PYTHON=py"& goto run
where python >nul 2>nul
if not errorlevel 1 set "ZY_PYTHON=python"& goto run

echo.
echo No Python runtime was found.
echo Please use a release archive that contains the runtime folder.
set "ZY_EXIT=1"
goto finish

:run
echo Starting installer...
"%ZY_PYTHON%" "scripts\install.py" %*
set "ZY_EXIT=%ERRORLEVEL%"

:finish
if not "%ZY_EXIT%"=="0" (
  echo.
  echo Installation failed. Check logs\server.log for details.
) else (
  echo.
  echo Installation completed. You can now load the browser-extension folder.
)
echo.
pause
exit /b %ZY_EXIT%
