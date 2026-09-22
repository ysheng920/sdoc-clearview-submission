@echo off
echo ========================================================
echo Starting SDOC-Clearview (Backend + Frontend)...
echo ========================================================

cd /d "%~dp0backend"
start "SDOC Clearview - Backend (:8000)" cmd /k "python -m uvicorn app.main:app --port 8000 --reload"

cd /d "%~dp0frontend"
start "SDOC Clearview - Frontend (:5173)" cmd /k "npm run dev"

echo.
echo Waiting for servers to initialize...
timeout /t 3 >nul
start http://localhost:5173

echo.
echo SDOC-Clearview is running!
echo Frontend: http://localhost:5173
echo Backend API: http://localhost:8000
echo.
pause
