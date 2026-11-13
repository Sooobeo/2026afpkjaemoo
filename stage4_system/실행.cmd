@echo off
chcp 65001 >nul
cd /d "%~dp0"
python run.py
if errorlevel 1 (
  echo 실행 오류가 있습니다. 위 메시지를 확인하세요.
  pause
  exit /b 1
)
start "" "outputs\latest\report.html"
