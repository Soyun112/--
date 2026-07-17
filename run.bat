@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title AI 어린이 안심 길찾기
echo.
echo ========================================
echo   AI 어린이 안심 길찾기 실행
echo ========================================
echo.

REM --- .env 준비 (.env.example 복사) ---
if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [안내] .env 가 없어 .env.example 을 복사했습니다.
    echo        메모장으로 .env 를 열어 [API 키] 칸을 채운 뒤
    echo        이 창을 닫고 run.bat 을 다시 실행하세요.
    echo        ^(키 없이도 MOCK 모드로 바로 실행은 가능합니다^)
    echo.
    choice /C YN /M "지금 MOCK 모드로 바로 실행할까요"
    if errorlevel 2 exit /b 0
  ) else (
    echo [오류] .env.example 파일이 없습니다.
    pause
    exit /b 1
  )
)

REM --- Python 확인 ---
where py >nul 2>&1
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo [오류] Python 이 설치되어 있지 않습니다.
    echo        https://www.python.org/downloads/ 에서 설치 후
    echo        "Add python.exe to PATH" 옵션을 켠 뒤 다시 실행하세요.
    pause
    exit /b 1
  )
)

REM --- 가상환경 ---
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/3] 가상환경 생성 중...
  %PY% -m venv "backend\.venv"
  if errorlevel 1 (
    echo [오류] 가상환경 생성 실패
    pause
    exit /b 1
  )
)

set "VENV_PY=backend\.venv\Scripts\python.exe"
set "VENV_PIP=backend\.venv\Scripts\pip.exe"

echo [2/3] 패키지 설치/확인 중...
"%VENV_PIP%" install -r "backend\requirements.txt" -q
if errorlevel 1 (
  echo [오류] pip install 실패
  pause
  exit /b 1
)

echo [3/3] 서버 시작 (http://127.0.0.1:8000)
echo       종료하려면 이 창을 닫으세요.
echo.

REM --- 프론트엔드 열기 (서버 기동 후) ---
start "" cmd /c "timeout /t 2 /nobreak >nul & start \"\" \"frontend\index.html\""

cd /d "%~dp0backend"
"%VENV_PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

echo.
echo 서버가 종료되었습니다.
pause
endlocal
