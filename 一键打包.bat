@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

echo ==============================================
echo   课表识别助手 - 一键打包
echo ==============================================
echo.

rem ---- 检查 Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)

rem ---- 检查 PyInstaller ----
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [提示] 未检测到 PyInstaller，正在安装...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败。
        pause
        exit /b 1
    )
)

rem ---- 打包 ----
echo [1/2] 正在打包，请稍候...
python -m PyInstaller --noconfirm --clean TimetableOCR.spec
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方日志。
    pause
    exit /b 1
)

set "VER=%~1"
if "%VER%"=="" (
    echo.
    echo 打包完成！产物目录：dist\TimetableOCR\
    echo 如需生成发布 zip，请带版本号运行，例如：一键打包.bat v0.2.4
    echo.
    pause
    exit /b 0
)

rem ---- 生成发布 zip ----
echo [2/2] 正在生成发布压缩包 TimetableOCR-%VER%-win64.zip ...
set "STAGE=dist\_stage"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
copy /y "dist\TimetableOCR\TimetableOCR.exe" "%STAGE%\课表识别.exe" >nul
xcopy /e /i /y "dist\TimetableOCR\_internal" "%STAGE%\_internal" >nul
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath 'dist\TimetableOCR-%VER%-win64.zip' -Force"
if errorlevel 1 (
    echo [错误] 生成压缩包失败。
    rmdir /s /q "%STAGE%"
    pause
    exit /b 1
)
rmdir /s /q "%STAGE%"

echo.
echo 全部完成！
echo   - 解压目录：dist\TimetableOCR\
echo   - 发布包：dist\TimetableOCR-%VER%-win64.zip
echo.
pause
endlocal
