: << 'CMDBLOCK'
@echo off
REM Cross-platform polyglot launcher for this plugin's hook scripts.
REM Pattern adapted from obra/superpowers (MIT), docs/windows/polyglot-hooks.md.
REM
REM On Windows: cmd.exe runs the batch block below, which locates bash and runs
REM the named hook script. On Unix: the shell treats the whole batch block as a
REM no-op heredoc and falls through to the shell section after CMDBLOCK.
REM
REM Hook scripts are extensionless ("session-start", not "session-start.sh")
REM because Claude Code on Windows prepends "bash" to any command containing
REM ".sh", which would break this dispatcher.
REM
REM A hook must never fail a session, so every path here exits 0.
REM
REM Usage: run-hook.cmd <script-name> [args...]

if "%~1"=="" exit /b 0

set "HOOK_DIR=%~dp0"

REM Git for Windows, standard locations first.
if exist "C:\Program Files\Git\bin\bash.exe" (
    "C:\Program Files\Git\bin\bash.exe" "%HOOK_DIR%%~1" %2 %3 %4 %5 %6 %7 %8 %9
    exit /b 0
)
if exist "C:\Program Files (x86)\Git\bin\bash.exe" (
    "C:\Program Files (x86)\Git\bin\bash.exe" "%HOOK_DIR%%~1" %2 %3 %4 %5 %6 %7 %8 %9
    exit /b 0
)

REM Then bash on PATH (non-default Git install, MSYS2, Cygwin).
where bash >nul 2>nul
if %ERRORLEVEL% equ 0 (
    bash "%HOOK_DIR%%~1" %2 %3 %4 %5 %6 %7 %8 %9
    exit /b 0
)

REM No bash: skip the hook silently. The plugin still works, it just does not
REM inject session context.
exit /b 0
CMDBLOCK

# Unix (and Git Bash on Windows): run the named script from this directory.
[ -n "${1:-}" ] || exit 0
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)" || exit 0
SCRIPT_NAME="$1"
shift
[ -r "${SCRIPT_DIR}/${SCRIPT_NAME}" ] || exit 0
bash "${SCRIPT_DIR}/${SCRIPT_NAME}" "$@" || true
exit 0
