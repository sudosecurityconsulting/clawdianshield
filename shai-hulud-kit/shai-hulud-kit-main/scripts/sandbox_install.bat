@echo off
REM sandbox_install.bat - vet a dep in a disposable venv before promoting it (Windows)
REM
REM Usage: scripts\sandbox_install.bat <package>==<version>
REM        scripts\sandbox_install.bat -r <requirements-file>

setlocal enabledelayedexpansion

if "%~1"=="" (
    echo Usage: %0 ^<package^>==^<version^>  or  %0 -r ^<requirements-file^>
    exit /b 3
)

REM Detect repo root
for /f "delims=" %%I in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%I"
if "%REPO_ROOT%"=="" set "REPO_ROOT=%CD%"

set "SANDBOX_DIR=%REPO_ROOT%\.sandbox-venv"

REM Warn about sensitive env vars
if defined AWS_ACCESS_KEY_ID echo ⚠ AWS_ACCESS_KEY_ID is set in this shell
if defined GITHUB_TOKEN echo ⚠ GITHUB_TOKEN is set in this shell
if defined GH_TOKEN echo ⚠ GH_TOKEN is set in this shell
if defined NPM_TOKEN echo ⚠ NPM_TOKEN is set in this shell
if defined ANTHROPIC_API_KEY echo ⚠ ANTHROPIC_API_KEY is set in this shell

REM Find Python
set "PY="
where python >nul 2>&1 && set "PY=python" & goto :found_py
where py >nul 2>&1 && set "PY=py -3.11" & goto :found_py
echo sandbox_install: no python found 1>&2
exit /b 3

:found_py

REM Clean up prior sandbox
if exist "%SANDBOX_DIR%" (
    echo sandbox_install: removing prior %SANDBOX_DIR%
    rmdir /S /Q "%SANDBOX_DIR%"
)

echo sandbox_install: creating %SANDBOX_DIR%...
%PY% -m venv "%SANDBOX_DIR%"
if errorlevel 1 (
    echo sandbox_install: venv creation failed 1>&2
    exit /b 3
)

set "SANDBOX_PY=%SANDBOX_DIR%\Scripts\python.exe"
set "SANDBOX_PIP=%SANDBOX_DIR%\Scripts\pip.exe"

REM Upgrade pip + install pip-audit
"%SANDBOX_PIP%" install --quiet --upgrade pip pip-audit

if "%~1"=="-r" (
    if not exist "%~2" (
        echo sandbox_install: requirements file not found: %~2 1>&2
        exit /b 3
    )
    set "REQ_FILE=%~2"
    
    REM Check for hashed file with Windows-only deps (we ARE on Windows, so it's fine)
    echo !REQ_FILE! | findstr /I "requirements-hashed.txt" >nul
    if not errorlevel 1 (
        echo sandbox_install: installing !REQ_FILE! with --require-hashes --only-binary :all:...
        "%SANDBOX_PIP%" install --only-binary :all: --require-hashes -r "!REQ_FILE!"
        if errorlevel 1 (
            echo sandbox_install: --require-hashes install failed; aborting ^(do NOT promote^) 1>&2
            exit /b 1
        )
    ) else (
        echo sandbox_install: installing !REQ_FILE! with --only-binary :all:...
        "%SANDBOX_PIP%" install --only-binary :all: -r "!REQ_FILE!"
        if errorlevel 1 (
            echo sandbox_install: --only-binary install failed; aborting 1>&2
            exit /b 1
        )
    )
) else (
    echo sandbox_install: installing %~1 with --only-binary :all:...
    "%SANDBOX_PIP%" install --only-binary :all: "%~1"
    if errorlevel 1 (
        echo sandbox_install: --only-binary install failed; aborting ^(do NOT promote^) 1>&2
        exit /b 1
    )
)

echo.
echo sandbox_install: running pip-audit against sandbox...
"%SANDBOX_PY%" -m pip_audit --strict --progress-spinner=off
set "AUDIT_CODE=%ERRORLEVEL%"

echo.
echo sandbox_install: installed packages:
"%SANDBOX_PIP%" list --format=columns

echo.
if %AUDIT_CODE%==0 (
    echo sandbox_install: clean. Safe to promote to real environment.
    echo   To clean up: rmdir /S /Q "%SANDBOX_DIR%"
    exit /b 0
) else (
    echo sandbox_install: findings. Do NOT promote to real environment.
    echo   Sandbox left at: %SANDBOX_DIR%
    exit /b 1
)
