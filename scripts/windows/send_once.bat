@echo off
setlocal

set "PROJECT_ROOT=%~dp0..\.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "CONFIG_PATH=%PROJECT_ROOT%\config.local.json"

if not exist "%PYTHON_EXE%" (
  echo 未找到 %PYTHON_EXE%
  echo 请先运行 scripts\windows\install.ps1
  exit /b 1
)

if not exist "%CONFIG_PATH%" (
  echo 未找到 %CONFIG_PATH%
  echo 请先复制 config.example.json 为 config.local.json 并填写配置
  exit /b 1
)

pushd "%PROJECT_ROOT%"
"%PYTHON_EXE%" -m screenshot_sender --once --config "%CONFIG_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
