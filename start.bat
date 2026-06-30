@echo off
echo ===================================================
echo     AUTO-STICKY-MAN STUDIO - STARTING SERVER...
echo ===================================================
echo.
echo Starting FastAPI Backend...
start "Auto-Sticky-Man Browser Launcher" cmd /c "timeout /t 2 >nul && start http://127.0.0.1:8088"
python -m uvicorn web.server:app --port 8088
pause
