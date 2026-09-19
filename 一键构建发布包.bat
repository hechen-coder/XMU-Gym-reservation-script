@echo off
title ôԶԤԼ - 
cd /d "%~dp0"
if exist "packaging\build_release.py" (
    set SCRIPT_PATH=packaging\build_release.py
) else (
    cd /d "%~dp0.."
    set SCRIPT_PATH=packaging\build_release.py
)

echo ==============================================================
echo        ôԶԤԼ - һ
echo ==============================================================
echo.
echo Զ̣Ժ...
echo.

python "%SCRIPT_PATH%"

if %errorlevel% neq 0 (
    echo.
    echo ==============================================================
    echo [] δ˳ɣϷĴʾ
    echo ==============================================================
    pause
    exit /b %errorlevel%
)

echo.
echo ==============================================================
echo [ɹ] ȫ˳ɣ
echo.
echo λλĿĿ¼ dist ļУ
echo   1. ɫѹð: dist\XMU_Gym_Booking\
echo   2. ⰲװѹ:   dist\XMU_Gym_Booking_v1.2.1_Portable_Windows_x64.zip
echo ==============================================================
echo.
pause
