@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [Paper2Data] Python не найден в PATH.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [Paper2Data] Создаю виртуальное окружение...
  python -m venv backend\.venv
  if errorlevel 1 (
    echo [Paper2Data] Не удалось создать venv.
    pause
    exit /b 1
  )
  backend\.venv\Scripts\python.exe -m pip install --upgrade pip
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
)

if exist "frontend\package.json" (
  if not exist "frontend\node_modules" (
    where npm >nul 2>nul
    if not errorlevel 1 (
      echo [Paper2Data] Устанавливаю зависимости frontend...
      pushd frontend
      call npm install
      popd
    )
  )
  if not exist "frontend\dist\index.html" (
    where npm >nul 2>nul
    if not errorlevel 1 (
      echo [Paper2Data] Собираю frontend...
      pushd frontend
      if exist "node_modules\esbuild\install.js" (
        node node_modules\esbuild\install.js >nul 2>nul
      )
      call npm run build
      popd
    )
  )
)

echo [Paper2Data] Запуск...
backend\.venv\Scripts\python.exe run.py %*
endlocal
