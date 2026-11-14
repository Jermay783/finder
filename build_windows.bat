@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (echo Installation failed & pause & exit /b 1)
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name US_Store_Finder_3_3 app.py
if errorlevel 1 (echo Build failed & pause & exit /b 1)
echo Ready: dist\US_Store_Finder_3_3.exe
pause
