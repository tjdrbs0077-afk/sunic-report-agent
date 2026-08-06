@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist .venv (
  echo [1/3] 가상환경 생성 중...
  python -m venv .venv
)
echo [2/3] 의존성 설치 중...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
echo [3/3] 서버 시작 — http://127.0.0.1:8020
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8020
