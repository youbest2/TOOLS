@echo off
REM ============================================================================
REM  run_sbsx_patch.bat  (Opus v4)  -  keep THIS file inside the project.
REM  Place it next to the "rhapsody_flowgen" folder, e.g.:
REM     <package>\run_sbsx_patch.bat
REM     <package>\rhapsody_flowgen\sbsx_patch_v109.py
REM  It auto-detects the package directory from its OWN location (%~dp0),
REM  so you never hardcode PKGDIR again.
REM
REM  Applies node text + positions + distinct decision ports to a Rhapsody 109
REM  diagram unit, using the sbsx_plan.json produced by the COM build.
REM  RAW-TEXT / RPY-ASCII safe. Dry-run first; writes a .bak before --write.
REM  CLOSE the Rhapsody project before running.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion

REM ---- EDIT THESE 3 (path to the model unit + diagram + project _rpy folder) --
set "DIAGRAM=AD_AdcAbs_Get_VBATT_MON"
set "PROJ_ROOT=D:\Sandbox\Nissan\Swee500\SWEET500_Repo\app-bootloader\FlashBootloader\FlashBootloader_SwDD\FlashBootloader_SwDD_rpy"
set "SBSX=%PROJ_ROOT%\FlashBootloader.sbsx"
REM ---------------------------------------------------------------------------

REM ---- AUTO-DETECT the package dir (folder that contains rhapsody_flowgen\sbsx_patch_v109.py)
set "PKGDIR="
for /f "delims=" %%F in ('dir /b /s "%~dp0sbsx_patch_v109.py" 2^>nul') do (
  set "HIT=%%~dpF"
)
if defined HIT (
  REM HIT = ...\rhapsody_flowgen\  -> strip the trailing "rhapsody_flowgen\"
  set "HIT=!HIT:~0,-1!"
  for %%P in ("!HIT!") do set "PKGDIR=%%~dpP"
  set "PKGDIR=!PKGDIR:~0,-1!"
)
if not defined PKGDIR set "PKGDIR=%~dp0"
if "%PKGDIR:~-1%"=="\" set "PKGDIR=%PKGDIR:~0,-1%"

set "PLAN=%PKGDIR%\rhapsody_flowgen\sbsx_plan.json"

REM Prefer a local venv if present.
set "PY=python"
if exist "%PKGDIR%\venv\Scripts\python.exe"  set "PY=%PKGDIR%\venv\Scripts\python.exe"
if exist "%PKGDIR%\.venv\Scripts\python.exe" set "PY=%PKGDIR%\.venv\Scripts\python.exe"

echo(
echo ============================================================================
echo  Rhapsody SBSX patcher (Opus v4, RPY-ASCII safe)
echo  Script  : %~f0
echo  Package : %PKGDIR%
echo  Diagram : %DIAGRAM%
echo  Unit    : %SBSX%
echo  Plan    : %PLAN%
echo  Python  : %PY%
echo ============================================================================

if not exist "%PKGDIR%\rhapsody_flowgen\sbsx_patch_v109.py" (
  echo [ERROR] Could not locate rhapsody_flowgen\sbsx_patch_v109.py under this script.
  echo         Put run_sbsx_patch.bat inside the package ^(next to rhapsody_flowgen^).
  goto :fail
)
if not exist "%PLAN%" (
  echo [ERROR] sbsx_plan.json not found: "%PLAN%"
  echo         Run the COM build first ^(python -m rhapsody_flowgen.main^).
  goto :fail
)

pushd "%PKGDIR%" || (echo [ERROR] cd failed & goto :fail)

echo(
echo --------------------------------------------------------------------------
echo [STEP 1/4] LOCATE the unit that actually holds the diagram's nodes
echo --------------------------------------------------------------------------
"%PY%" -m rhapsody_flowgen.sbsx_patch_v109 locate --root "%PROJ_ROOT%" --diagram "%DIAGRAM%"
if errorlevel 1 goto :popfail
echo(
echo  ^>^> If "PATCH THIS" points to a DIFFERENT .sbsx than SBSX above, press
echo     Ctrl+C, set SBSX to that file, and re-run.

echo(
echo --------------------------------------------------------------------------
echo [STEP 2/4] INSPECT the target unit (no changes)
echo --------------------------------------------------------------------------
"%PY%" -m rhapsody_flowgen.sbsx_patch_v109 inspect --sbsx "%SBSX%" --diagram "%DIAGRAM%"
if errorlevel 1 goto :popfail
echo(
echo  ^>^> Expect N ^> 0 scoped nodes, each with a transform. If N==0, the nodes
echo     are in another unit (STEP 1). Do NOT continue.

echo(
set /p GO1=Proceed to DRY-RUN patch? [Y/N] 
if /I not "!GO1!"=="Y" goto :cancelled

echo(
echo --------------------------------------------------------------------------
echo [STEP 3/4] PATCH (DRY-RUN, nothing written)
echo --------------------------------------------------------------------------
"%PY%" -m rhapsody_flowgen.sbsx_patch_v109 patch --sbsx "%SBSX%" --diagram "%DIAGRAM%" --plan "%PLAN%"
if errorlevel 1 goto :popfail
echo(
echo  ^>^> Review: actions should say body=ok pos=ok; diamonds body=n/a pos=ok;
echo     EDGEs ports=ok.

echo(
echo  [!] Make sure the Rhapsody project is CLOSED before writing.
set /p GO2=Apply for real (writes a .bak, then edits the unit)? [Y/N] 
if /I not "!GO2!"=="Y" goto :cancelled

echo(
echo --------------------------------------------------------------------------
echo [STEP 4/4] PATCH (WRITE)  - byte-exact .bak is created first
echo --------------------------------------------------------------------------
"%PY%" -m rhapsody_flowgen.sbsx_patch_v109 patch --sbsx "%SBSX%" --diagram "%DIAGRAM%" --plan "%PLAN%" --write
if errorlevel 1 goto :popfail

echo(
echo ============================================================================
echo  DONE. Backup saved as "%SBSX%.bak".
echo  Reopen the project in Rhapsody. If anything looks off, restore the .bak:
echo     copy /Y "%SBSX%.bak" "%SBSX%"
echo ============================================================================
popd
goto :end

:cancelled
echo(
echo Cancelled by user. No changes were written.
popd
goto :end

:popfail
echo(
echo [ERROR] A step failed (see above). If STEP 4 ran, restore "%SBSX%.bak".
popd
goto :fail

:fail
endlocal & exit /b 1
:end
endlocal & exit /b 0
