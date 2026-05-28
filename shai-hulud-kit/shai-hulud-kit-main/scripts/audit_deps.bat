@echo off
REM audit_deps.bat - local pip-audit driver (Windows)
REM Walks the repo for requirements files and runs pip-audit on each.

setlocal enabledelayedexpansion

REM Find Python
set "PY="
for %%P in (.venv311\Scripts\python.exe .venv\Scripts\python.exe venv\Scripts\python.exe) do (
    if exist "%%P" set "PY=%%P" & goto :found_py
)
where python >nul 2>&1 && set "PY=python" & goto :found_py
where py >nul 2>&1 && set "PY=py -3.11" & goto :found_py

echo audit_deps: no python found 1>&2
exit /b 3

:found_py
echo audit_deps: using %PY%

REM Ensure pip-audit is installed
%PY% -m pip_audit --version >nul 2>&1
if errorlevel 1 (
    echo audit_deps: pip-audit not installed; installing... 1>&2
    %PY% -m pip install --quiet pip-audit
    if errorlevel 1 (
        echo audit_deps: failed to install pip-audit 1>&2
        exit /b 3
    )
)

REM Find requirements files
set "FAILED=0"
set "FOUND=0"
for /R %%F in (requirements*.txt) do (
    set "F=%%F"
    REM Skip venv/node_modules/site-packages
    echo !F! | findstr /I "node_modules \.venv venv\\ \.tox site-packages" >nul
    if errorlevel 1 (
        set /a FOUND+=1
        echo.
        echo === Auditing %%F ===
        %PY% -m pip_audit -r "%%F" --strict --progress-spinner=off
        if errorlevel 1 (
            set "FAILED=1"
            echo   ^ findings in %%F
        )
    )
)

if %FOUND%==0 (
    echo audit_deps: no requirements files found
    exit /b 0
)

echo.
if %FAILED%==1 (
    echo audit_deps: FAIL -- see findings above
    echo Remediation: see docs\security\HARDENING.md ^(if present^)
    exit /b 1
)

echo audit_deps: PASS
exit /b 0
