@echo off
title 厦大体育馆自动预约工具 - 构建独立发布包
cd /d "%~dp0"
if exist "packaging\build_release.py" (
    set SCRIPT_PATH=packaging\build_release.py
) else (
    cd /d "%~dp0.."
    set SCRIPT_PATH=packaging\build_release.py
)

echo ==============================================================
echo        厦大体育馆自动预约工具 - 本地一键打包发布程序
echo ==============================================================
echo.
echo 正在启动自动化构建流程，请稍候...
echo.

python "%SCRIPT_PATH%"

if %errorlevel% neq 0 (
    echo.
    echo ==============================================================
    echo [错误] 打包构建未顺利完成，请检查上方的错误提示。
    echo ==============================================================
    pause
    exit /b %errorlevel%
)

echo.
echo ==============================================================
echo [成功] 打包发布流程已全部顺利完成！
echo.
echo 产物生成位置位于项目根目录的 dist 文件夹中：
echo   1. 绿色解压即用版: dist\XMU_Gym_Booking\
echo   2. 免安装压缩包:   dist\XMU_Gym_Booking_v1.1.2_Portable_Windows_x64.zip
echo ==============================================================
echo.
pause
