@echo off
REM Wrapper for goodreads-writer.py on Windows (venv-aware)
REM Usage: goodreads-write.bat <command> [args...]
REM Example: goodreads-write.bat rate 40121378 5

set "SCRIPT_DIR=%~dp0"
set "WRITER=%SCRIPT_DIR%goodreads-writer.py"

REM Prefer GR_VENV, then scripts\.venv, then system python
if defined GR_VENV if exist "%GR_VENV%\Scripts\activate.bat" (
    call "%GR_VENV%\Scripts\activate.bat"
) else if exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
)

python "%WRITER%" %*
