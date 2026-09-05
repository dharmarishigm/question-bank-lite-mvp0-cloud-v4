@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo Creating Python environment...
  py -3 -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if not exist .env (
  copy .env.example .env >nul
  echo Created .env. Add GCP values later to enable AI extraction.
)
if not exist data\uploads mkdir data\uploads
if not exist data\sources mkdir data\sources
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
