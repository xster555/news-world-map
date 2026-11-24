@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"

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

echo.
echo   新闻世界地图 - 本地服务
echo   地址: http://127.0.0.1:%PORT%/
echo   按 Ctrl+C 或关闭本窗口即可停止。
echo.
%PY% -m http.server %PORT% --directory web
pause
