@echo off
REM ============================================================================
REM  run_all.bat  (Opus v4 - multi-diagram)  - keep inside the package root.
REM  Builds ALL diagrams listed in config.yaml (COM), then post-processes ALL
REM  of them (SBSX: text + positions + routing + [YES]/[NO] guards).
REM  Self-locating; RPY-ASCII safe; dry-run before write; one .bak per unit.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion

set "CONFIG=config.yaml"

REM ---- AUTO-DETECT package dir (folder that contains rhapsody_flowgen\patch_all.py)
set "PKGDIR="
for /f "delims=" %%F in ('dir /b /s "%~dp0patch_all.py" 2^>nul') do set "HIT=%%~dpF"
if defined HIT (
  set "HIT=!HIT:~0,-1!"
  for %%P in ("!HIT!") do set "PKGDIR=%%~dpP"
  set "PKGDIR=!PKGDIR:~0,-1!"
)
if not defined PKGDIR set "PKGDIR=%~dp0"
if "%PKGDIR:~-1%"=="\" set "PKGDIR=%PKGDIR:~0,-1%"

set "CFGPATH=%PKGDIR%\rhapsody_flowgen\%CONFIG%"
set "PY=python"
if exist "%PKGDIR%\venv\Scripts\python.exe"  set "PY=%PKGDIR%\venv\Scripts\python.exe"
if exist "%PKGDIR%\.venv\Scripts\python.exe" set "PY=%PKGDIR%\.venv\Scripts\python.exe"

echo(
echo ============================================================================
echo  Rhapsody FlowGen - MULTI-DIAGRAM run (Opus v4)
echo  Package : %PKGDIR%
echo  Config  : %CFGPATH%
echo  Python  : %PY%
echo ============================================================================
if not exist "%PKGDIR%\rhapsody_flowgen\patch_all.py" (
  echo [ERROR] rhapsody_flowgen\patch_all.py not found under this script.
  goto :fail
)
if not exist "%CFGPATH%" (
  echo [ERROR] config not found: "%CFGPATH%"
  goto :fail
)

pushd "%PKGDIR%" || (echo [ERROR] cd failed & goto :fail)

echo(
echo --------------------------------------------------------------------------
echo [1/3] COM BUILD all diagrams  (Rhapsody must be RUNNING)
echo --------------------------------------------------------------------------
echo  This opens the project, builds each AD, saves and closes the project.
set /p GOB=Run the COM build now? [Y/N] 
if /I "!GOB!"=="Y" (
  "%PY%" -m rhapsody_flowgen.batch_main --config "%CFGPATH%"
  if errorlevel 1 (
    echo [WARN] COM build reported an error. You may still patch already-built diagrams.
  )
) else (
  echo  Skipping COM build ^(assuming diagrams already built and plans present^).
)

echo(
echo  [!] Ensure the Rhapsody PROJECT is CLOSED before patching (File ^> Close).
pause

echo(
echo --------------------------------------------------------------------------
echo [2/3] PATCH all diagrams  (DRY-RUN, nothing written)
echo --------------------------------------------------------------------------
"%PY%" -m rhapsody_flowgen.patch_all --config "%CFGPATH%"
if errorlevel 1 goto :popfail

echo(
set /p GOW=Apply for real now (writes one .bak per unit)? [Y/N] 
if /I not "!GOW!"=="Y" goto :cancelled

echo(
echo --------------------------------------------------------------------------
echo [3/3] PATCH all diagrams  (WRITE)
echo --------------------------------------------------------------------------
"%PY%" -m rhapsody_flowgen.patch_all --config "%CFGPATH%" --write
if errorlevel 1 goto :popfail

echo(
echo ============================================================================
echo  DONE. Reopen the project in Rhapsody. Restore any *.sbsx.bak to revert.
echo ============================================================================
popd
goto :end

:cancelled
echo Cancelled. No changes written.
popd
goto :end
:popfail
echo [ERROR] A step failed (see above). Restore *.sbsx.bak if a write occurred.
popd
goto :fail
:fail
endlocal & exit /b 1
:end
endlocal & exit /b 0
