@echo off
chcp 65001 >nul
title 厦大体育馆自动预约工具 - 构建独立发布包与安装程序

echo ==============================================================
echo        厦大体育馆自动预约工具 - 本地一键打包发布程序
echo ==============================================================
echo.
echo 即将执行自动化构建流水线：
echo  1. 检查 Python 及 PyInstaller 打包环境
echo  2. 自动收集 ddddocr 离线 OCR 模型与运行库
echo  3. 编译生成免安装独立运行目录 (dist/XMU_Gym_Booking)
echo  4. 压缩生成绿色免安装版 (dist/XMU_Gym_Booking_v1.0.0_Portable.zip)
echo  5. 探测 Inno Setup 并自动生成安装向导程序 (dist/XMU_Gym_Booking_Setup.exe)
echo.
echo ==============================================================
echo.

cd /d "%~dp0.."
python packaging\build_release.py

if %errorlevel% neq 0 (
    echo.
    echo ❌ [错误] 构建未完成，请检查上方的错误信息提示。
    pause
    exit /b %errorlevel%
)

echo.
echo 提示：构建成功！您可以在项目根目录下的 dist/ 文件夹查看构建出的安装包与压缩包。
echo.
pause
