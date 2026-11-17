@echo off
title ATLAS AI Platform Launcher
echo Starting ATLAS Backend API (http://127.0.0.1:8000)...
start "ATLAS Backend API" cmd /k "cd /d "%~dp0backend" && uv run uvicorn atlas.api:app --host 127.0.0.1 --port 8000"

echo Starting ATLAS Background Worker...
start "ATLAS Worker" cmd /k "cd /d "%~dp0backend" && uv run python -m atlas.worker"

echo Starting ATLAS Frontend Dashboard (http://localhost:3000)...
start "ATLAS Frontend Dashboard" cmd /k "cd /d "%~dp0frontend" && npm run start -- -p 3000"

echo All services launched! Open http://localhost:3000 in your browser.
