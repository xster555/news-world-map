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
echo   ============================================
echo    新闻世界地图   News World Map
echo   ============================================
echo.
echo    本地地址:  http://127.0.0.1:%PORT%/
echo    正在启动本地服务，并在后台采集最新新闻...
echo    采集日志:  collect.log
echo.
echo    关闭标题为「新闻世界地图 - 本地服务」的那个窗口即可停止服务。
echo.
start "新闻世界地图 - 本地服务" cmd /k "%PY% -m http.server %PORT% --directory web"
timeout /t 2 /nobreak >nul

echo   正在采集最新新闻（首次可能需要 10-40 秒）...
echo.
%PY% -m collector.collect

echo.
echo   正在发布数据快照到 web\data ...
%PY% scripts\publish.py

echo.
echo   采集完成。回到浏览器刷新一下即可看到最新数据。
echo.
pause
