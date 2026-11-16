@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw wechat_snip.py --once
) else (
  start "" python wechat_snip.py --once
)
