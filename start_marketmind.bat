@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else if exist ".venv\bin\python" (
  set "PYTHON=.venv\bin\python"
) else (
  set "PYTHON=python"
)

if "%MARKETMIND_HOME%"=="" set "MARKETMIND_HOME=%CD%\runtime"
set "MARKETMIND_MODE=work"
set "MARKETMIND_DATA_DIR=%MARKETMIND_HOME%"
set "MARKETMIND_WORKSPACE_DIR=%MARKETMIND_HOME%\projects"
set "DATABASE_URL=sqlite+aiosqlite:///%MARKETMIND_HOME:\=/%/database/marketmind.db"
set "LOG_FILE=%MARKETMIND_HOME%\logs\marketmind.log"
set "SCRAPE_ATTEMPTS_JSONL=%MARKETMIND_HOME%\logs\scrape_attempts.jsonl"
set "BLOCK_PATTERNS_JSONL=%MARKETMIND_HOME%\logs\blocked_patterns.jsonl"

set "MARKETMIND_MCP_ENABLED=1"
set "MARKETMIND_MCP_COMMAND_JSON=[""%PYTHON%"",""mcp_server.py""]"
set "MARKETMIND_MCP_TIMEOUT=30"

mkdir "%MARKETMIND_HOME%\database" 2>nul
mkdir "%MARKETMIND_HOME%\projects" 2>nul
mkdir "%MARKETMIND_HOME%\uploads" 2>nul
mkdir "%MARKETMIND_HOME%\exports" 2>nul
mkdir "%MARKETMIND_HOME%\reports" 2>nul
mkdir "%MARKETMIND_HOME%\backups" 2>nul
mkdir "%MARKETMIND_HOME%\logs" 2>nul

echo РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ
echo MARKETMIND_HOME=%MARKETMIND_HOME%
echo MCP сервер: включен
%PYTHON% -m app.runtime_cli backup-if-needed
echo Откройте: http://127.0.0.1:18080/projects
echo Для безопасной остановки нажмите Ctrl+C в этом окне.

%PYTHON% -m uvicorn app.web.app:create_app --factory --host 127.0.0.1 --port 18080
