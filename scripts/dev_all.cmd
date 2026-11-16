@echo off
REM ============================================================
REM scripts/dev_all.cmd
REM
REM Khoi dong dong thoi FastAPI backend (port 8000) va Next.js
REM frontend (port 3000) tren may Windows.
REM
REM Cach dung:
REM   scripts\dev_all.cmd            # chay ca hai (mac dinh)
REM   scripts\dev_all.cmd install    # pip install + npm install (idempotent)
REM   scripts\dev_all.cmd stop       # dung moi tien trinh BE/FE dang chay
REM   scripts\dev_all.cmd backend    # chi chay FastAPI
REM   scripts\dev_all.cmd frontend   # chi chay Next.js
REM
REM Phim tat:
REM   Ctrl+C trong cua so nay se goi stop() truoc khi thoat.
REM ============================================================

setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%" >nul

set "PYTHON_CMD="
py -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py"
) else (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if "%PYTHON_CMD%"=="" (
    echo [ERR] Khong tim thay Python! Vui long cai dat Python 3.10+ hoac kiem tra PATH.
    popd >nul
    endlocal & exit /b 1
)

if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8000"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=3000"
set "API_TARGET=http://127.0.0.1:%BACKEND_PORT%"
set "BACKEND_LOG=%~dp0backend.log"
set "FRONTEND_LOG=%~dp0frontend.log"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=both"
if /I "%MODE%"=="install" goto :install
if /I "%MODE%"=="stop" goto :stop

call :ensure_deps
if errorlevel 1 goto :end

if /I "%MODE%"=="backend" goto :backend
if /I "%MODE%"=="frontend" goto :frontend

:both
call :kill_port %BACKEND_PORT%
call :kill_port %FRONTEND_PORT%
call :start_backend
call :start_frontend
goto :wait

:backend
call :kill_port %BACKEND_PORT%
call :start_backend
goto :wait

:frontend
call :kill_port %FRONTEND_PORT%
call :start_frontend
goto :wait

:wait
call :wait_console
goto :shutdown

:wait_console
echo.
echo Dang cho cac dich vu khoi dong...
echo Logs: %BACKEND_LOG%  /  %FRONTEND_LOG%
echo.

call :wait_for_startup
if errorlevel 1 goto :eof

echo Nhan Ctrl+C trong cua so nay de dung.

:wait_loop
call :port_up %BACKEND_PORT%
set "BACKEND_UP=!ERRORLEVEL!"
call :port_up %FRONTEND_PORT%
set "FRONTEND_UP=!ERRORLEVEL!"

if /I "%MODE%"=="backend" if "!BACKEND_UP!"=="0" goto :wait_tick
if /I "%MODE%"=="frontend" if "!FRONTEND_UP!"=="0" goto :wait_tick
if /I "%MODE%"=="both" if "!BACKEND_UP!"=="0" if "!FRONTEND_UP!"=="0" goto :wait_tick

echo.
echo [ERR] Mot tien trinh da dung bat thuong!
if /I not "%MODE%"=="frontend" if not "!BACKEND_UP!"=="0" echo  - Backend FastAPI tren cong %BACKEND_PORT% da dung!
if /I not "%MODE%"=="backend" if not "!FRONTEND_UP!"=="0" echo  - Frontend Next.js tren cong %FRONTEND_PORT% da dung!
echo Xem log trong thu muc scripts:
echo   BE: %BACKEND_LOG%
echo   FE: %FRONTEND_LOG%
goto :eof

:wait_tick
ping 127.0.0.1 -n 3 >nul
goto :wait_loop

:wait_for_startup
set "STARTUP_TIMEOUT=60"
set "STARTUP_COUNT=0"
echo Dang cho cac tien trinh san sang (toi da %STARTUP_TIMEOUT%s)...

:startup_poll
set "BE_READY=1"
set "FE_READY=1"

if /I "%MODE%"=="frontend" goto :poll_fe
call :port_up %BACKEND_PORT%
if errorlevel 1 set "BE_READY=0"

:poll_fe
if /I "%MODE%"=="backend" goto :poll_check
call :port_up %FRONTEND_PORT%
if errorlevel 1 set "FE_READY=0"

:poll_check
if "!BE_READY!"=="1" if "!FE_READY!"=="1" goto :startup_ready

set /a STARTUP_COUNT+=1
if !STARTUP_COUNT! GEQ !STARTUP_TIMEOUT! goto :startup_timeout

ping 127.0.0.1 -n 2 >nul
goto :startup_poll

:startup_ready
echo.
echo ===========================================================
echo  Dich vu da san sang!
if /I not "%MODE%"=="frontend" echo  BE:  http://127.0.0.1:%BACKEND_PORT%/api/health
if /I not "%MODE%"=="backend"  echo  FE:  http://127.0.0.1:%FRONTEND_PORT%/
echo  Logs: %BACKEND_LOG%
echo        %FRONTEND_LOG%
echo  Ctrl+C de dung ca hai.
echo ===========================================================
echo.
exit /b 0

:startup_timeout
echo.
echo [ERR] Khoi dong that bai: Tien trinh khong mo port sau %STARTUP_TIMEOUT% giay!
if /I not "%MODE%"=="frontend" if "!BE_READY!"=="0" echo  - Backend tren port %BACKEND_PORT% CHUA san sang!
if /I not "%MODE%"=="backend" if "!FE_READY!"=="0" echo  - Frontend tren port %FRONTEND_PORT% CHUA san sang!
echo.
if /I "%MODE%"=="frontend" goto :timeout_fe_log
if "!BE_READY!"=="1" goto :timeout_fe_log
echo === Log Backend: %BACKEND_LOG% ===
if exist "%BACKEND_LOG%" (
    "%PYTHON_CMD%" -c "import sys; p=sys.argv[1]; lines=open(p, encoding='utf-8', errors='ignore').readlines(); print(''.join(lines[-20:]), end='')" "%BACKEND_LOG%" 2>nul
)
echo.

:timeout_fe_log
if /I "%MODE%"=="backend" goto :timeout_finish
if "!FE_READY!"=="1" goto :timeout_finish
echo === Log Frontend: %FRONTEND_LOG% ===
if exist "%FRONTEND_LOG%" (
    "%PYTHON_CMD%" -c "import sys; p=sys.argv[1]; lines=open(p, encoding='utf-8', errors='ignore').readlines(); print(''.join(lines[-20:]), end='')" "%FRONTEND_LOG%" 2>nul
)
echo.

:timeout_finish
exit /b 1

:port_up
netstat -ano | findstr /R /C:":%~1[ ].*LISTENING" >nul
goto :eof

:shutdown
call :stop
popd >nul
endlocal
exit /b 0

:install
echo Cai dat dependencies Python va Node...
"%PYTHON_CMD%" -m pip install --disable-pip-version-check -r "%PROJECT_ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERR] pip install that bai.
    popd >nul
    endlocal & exit /b 1
)
rem pyobjc-framework-Cocoa chi build duoc tren macOS; thu cung khong loi tren Windows nho marker sys_platform.
if "%OS%"=="" goto :skip_macos
echo %OS% | findstr /I "Windows" >nul
if not errorlevel 1 goto :skip_macos
"%PYTHON_CMD%" -m pip install --disable-pip-version-check -r "%PROJECT_ROOT%\requirements-macos.txt"
if errorlevel 1 (
    echo [WARN] requirements-macos.txt that bai. Bo qua neu ban khong tren macOS.
)
:skip_macos
pushd "%PROJECT_ROOT%\frontend" >nul
if exist package.json (
    call npm.cmd install --no-audit --no-fund
    if errorlevel 1 (
        echo [ERR] npm install that bai.
        popd >nul
        popd >nul
        endlocal & exit /b 1
    )
)
popd >nul
echo Cai dat xong.
popd >nul
endlocal & exit /b 0

:stop
echo Dang dung moi tien trinh BE/FE...
call :kill_port %BACKEND_PORT%
call :kill_port %FRONTEND_PORT%
popd >nul
endlocal & exit /b 0

:start_backend
echo Khoi dong backend FastAPI tren cong %BACKEND_PORT% ...
set "PYTHONIOENCODING=utf-8"
>"%BACKEND_LOG%" echo [%date% %time%] Starting backend on 127.0.0.1:%BACKEND_PORT%
start "" /B %PYTHON_CMD% -m uvicorn src.web.app:app --host 127.0.0.1 --port %BACKEND_PORT% --log-level info >>"%BACKEND_LOG%" 2>&1
goto :eof

:start_frontend
echo Khoi dong frontend Next.js tren cong %FRONTEND_PORT% ...
set "NEXT_PUBLIC_API_TARGET=%API_TARGET%"
pushd "%PROJECT_ROOT%\frontend" >nul
if exist ".next\BUILD_ID" goto :run_frontend

echo Chua co production build. Dang build frontend...
call npm.cmd run build >"%FRONTEND_LOG%" 2>&1
if errorlevel 1 (
    echo [ERR] next build that bai. Xem %FRONTEND_LOG%.
    popd >nul
    goto :err
)

:run_frontend
>"%FRONTEND_LOG%" echo [%date% %time%] Starting frontend on 127.0.0.1:%FRONTEND_PORT%
start "" /B cmd.exe /c "call npm.cmd run start" >>"%FRONTEND_LOG%" 2>&1
popd >nul
goto :eof

:err
popd >nul
endlocal & exit /b 1

:kill_port
set "PORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT%[ ].*LISTENING"') do (
    taskkill /F /T /PID %%P >nul 2>&1
)
goto :eof

:ensure_deps
"%PYTHON_CMD%" -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Thieu dependency Python. Chay: scripts\dev_all.cmd install
)
if exist "%PROJECT_ROOT%\frontend\node_modules" goto :eof
echo [WARN] Chua co node_modules. Chay: scripts\dev_all.cmd install
goto :eof

:end
popd >nul
endlocal & exit /b 1
