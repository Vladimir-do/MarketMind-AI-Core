@echo off
setlocal
cd /d "%~dp0"

:menu
echo ==========================================
echo  Parser Agent launcher
echo ==========================================
echo.
echo  1. Start Telegram bot
echo  2. Update prices once
echo  3. Show last parsing metrics
echo  4. Run tests
echo  5. Install/update dependencies
echo  6. Open Ozon browser profile
echo  7. Generate HTML report
echo  8. Deploy WB Cloud Function
echo  0. Exit
echo.

set /p choice="Choose action: "

if "%choice%"=="1" goto bot
if "%choice%"=="2" goto update
if "%choice%"=="3" goto metrics
if "%choice%"=="4" goto tests
if "%choice%"=="5" goto deps
if "%choice%"=="6" goto ozon_profile
if "%choice%"=="7" goto report
if "%choice%"=="8" goto deploy_wb
if "%choice%"=="0" goto end

echo Unknown choice.
call :after_action
goto menu

:bot
echo Starting Telegram bot...
py -3.11 -m app.main --telegram
call :after_action
goto menu

:update
echo Updating prices once...
py -3.11 -m app.main --update
call :after_action
goto menu

:metrics
echo Showing last parsing metrics...
py -3.11 -m app.main --metrics 20
call :after_action
goto menu

:tests
echo Running tests...
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
call :after_action
goto menu

:deps
echo Installing Python dependencies...
py -3.11 -m pip install -r requirements.txt
echo Installing Playwright Chromium...
py -3.11 -m playwright install chromium
call :after_action
goto menu

:ozon_profile
echo Opening visible Ozon browser profile (manual login/captcha warm-up)...
py -3.11 -m app.main --ozon-login
call :after_action
goto menu

:report
echo Generating HTML report with embedded images...
py -3.11 -m app.main --report --embed-images
call :after_action
goto menu

:deploy_wb
echo Deploying WB Cloud Function to Yandex Cloud...
py -3.11 -m app.main --deploy-wb
call :after_action
goto menu

:after_action
echo.
echo Task finished. Exit code: %ERRORLEVEL%
echo Press any key to return to the launcher menu...
pause >nul
echo.
exit /b

:end
endlocal
