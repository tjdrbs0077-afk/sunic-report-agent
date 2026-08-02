#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "[1/3] 가상환경 생성 중..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "[2/3] 의존성 설치 중..."
python -m pip install -q -r requirements.txt
echo "[3/3] 서버 시작 — http://127.0.0.1:8020"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8020
