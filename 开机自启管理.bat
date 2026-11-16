@echo off
setlocal
cd /d "%~dp0"
title WeSnip Autostart Manager

set "RUNKEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "VALNAME=WeSnip"

:menu
cls
echo ==================================================
echo           WeSnip Startup Manager
echo ==================================================
echo.
reg query "%RUNKEY%" /v %VALNAME% >nul 2>nul
if %errorlevel%==0 (
  echo   Status : [ENABLED] runs at logon
  for /f "tokens=2,*" %%a in ('reg query "%RUNKEY%" /v %VALNAME% ^| findstr /i "%VALNAME%"') do echo   Value  : %%b
) else (
  echo   Status : [DISABLED]
)
echo.
echo   1. Enable autostart (overwrite existing)
echo   2. Disable autostart
echo   0. Exit
echo.
set "choice="
set /p choice=Enter your choice:
if "%choice%"=="1" goto enable
if "%choice%"=="2" goto disable
if "%choice%"=="0" exit /b 0
echo.
echo   [Invalid input] Enter 1, 2 or 0.
pause
exit /b 0

:enable
if not exist "%~dp0WeSnip.exe" (
  echo.
  echo   [Error] WeSnip.exe not found. Put this bat in the same folder as WeSnip.exe.
  pause
  goto menu
)
reg add "%RUNKEY%" /v %VALNAME% /t REG_SZ /d "\"%~dp0WeSnip.exe\" --daemon" /f >nul
if %errorlevel%==0 (
  echo.
  echo   [OK] Autostart set: "%~dp0WeSnip.exe" --daemon
) else (
  echo.
  echo   [FAILED] Could not write registry. Check permissions.
)
echo.
pause
goto menu

:disable
reg delete "%RUNKEY%" /v %VALNAME% /f >nul 2>nul
if %errorlevel%==0 (
  echo.
  echo   [OK] Autostart removed.
) else (
  echo.
  echo   [Note] No autostart entry existed.
)
echo.
pause
goto menu