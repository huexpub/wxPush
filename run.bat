@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [wxpush] 正在创建虚拟环境 .venv ...
  python -m venv .venv
  if errorlevel 1 goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -e ".[dev]"
  if errorlevel 1 goto :fail
)

if not exist "wxpush\static\index.html" (
  if exist "web\package.json" (
    echo [wxpush] 前端还没有构建，正在 npm install ^&^& npm run build ...
    pushd web
    call npm install
    if errorlevel 1 (popd & goto :fail)
    call npm run build
    if errorlevel 1 (popd & goto :fail)
    popd
  )
)

if "%WXPUSH_DATA_DIR%"=="" set WXPUSH_DATA_DIR=%~dp0data
if "%WXPUSH_HOST%"=="" set WXPUSH_HOST=127.0.0.1

echo [wxpush] http://%WXPUSH_HOST%:8000
".venv\Scripts\python.exe" -m wxpush serve --host %WXPUSH_HOST% --port 8000
goto :eof

:fail
echo [wxpush] 初始化失败，请检查 Python / Node 是否在 PATH 中
exit /b 1
