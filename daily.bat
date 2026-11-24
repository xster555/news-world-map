@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo.
  echo   [X] 没有找到可用的 Python
  echo.
  echo   请先安装 Python 3.8 或更高版本，安装时务必勾选 "Add python.exe to PATH"
  echo   下载地址: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
%PY% -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [X] Python 版本过低，需要 3.8 或更高。
  echo.
  pause
  exit /b 1
)

echo   正在采集最新新闻...
%PY% -m collector.collect > collect.log 2>&1
type collect.log
echo.
echo   正在发布数据快照到 web\data ...
%PY% scripts\publish.py
echo.
echo   完成。结果见 collect.log 与 data\news.json
echo.
pause
