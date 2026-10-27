@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo 找不到 Python Launcher。請安裝 Python 3，並勾選 Python Launcher。
    pause
    exit /b 1
)

py -3 refresh_data.py
if errorlevel 1 (
    echo.
    echo 更新失敗，index.html 保持原樣。
    pause
    exit /b 1
)

echo.
echo 正在瀏覽器開啟更新後的頁面…
start "" "%~dp0index.html"
endlocal
