@echo off
setlocal EnableExtensions
title Shadetree
rem Shadetree launcher: starts the read-only live console and opens it in the web browser.
rem The Desktop shortcuts run this file. You can also run it yourself with words after it:
rem   shadetree-start.bat               the car, through the OBDLink adapter
rem   shadetree-start.bat demo          a simulated car, no adapter needed
rem   shadetree-start.bat phone         also let a phone on the same Wi-Fi open the console
rem   shadetree-start.bat 2             pin the protocol: 2 = J1850 VPW (GM), 1 = J1850 PWM (Ford),
rem                                     3 = ISO 9141, 5 or 4 = KWP, 6 = CAN; 0 = automatic (the default)
rem   shadetree-start.bat COM5          use this adapter port (it is remembered)
rem Words can be combined, for example: shadetree-start.bat phone 2

set "APP=%LOCALAPPDATA%\Shadetree"
set "ST_EXE=%APP%\venv\Scripts\shadetree-ai.exe"
set "DEMO="
set "PHONE="
set "PORTARG="
set "PROTO=0"

:args
if "%~1"=="" goto argsdone
set "A=%~1"
shift
if /i "%A%"=="demo" (set "DEMO=1" & goto args)
if /i "%A%"=="phone" (set "PHONE=1" & goto args)
echo %A%| findstr /r /i /x "COM[0-9][0-9]*" >nul && (set "PORTARG=%A%" & goto args)
echo %A%| findstr /r /i /x "[0-9ABC]" >nul && (set "PROTO=%A%" & goto args)
echo I do not understand "%A%".
echo Use demo, phone, a protocol number such as 2, or a port such as COM5.
goto done

:argsdone
if not exist "%ST_EXE%" goto notinstalled
if not exist "%APP%\install-windows.ps1" goto notinstalled
if defined DEMO goto run

:find
echo Looking for the OBDLink adapter...
if defined PORTARG (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\install-windows.ps1" -FindPort -Port %PORTARG%
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\install-windows.ps1" -FindPort
)
if errorlevel 1 goto noport
set /p ST_PORT=<"%APP%\port.txt"
goto run

:noport
echo.
echo Without the adapter Shadetree cannot read the car. You can try the demo instead.
choice /c DRQ /n /m "Press D for the demo (a simulated car), R to look for the adapter again, or Q to quit: "
if errorlevel 3 goto end
if errorlevel 2 goto find
set "DEMO=1"

:run
set "ST_ARGS=console --protocol %PROTO%"
if defined DEMO set "ST_ARGS=%ST_ARGS% --demo"
if not defined DEMO set "ST_ARGS=%ST_ARGS% --port %ST_PORT%"
if defined PHONE set "ST_ARGS=%ST_ARGS% --host 0.0.0.0 --allow-lan"
echo.
echo ==========================================================================
echo  Shadetree console. Read-only: it never clears codes or changes the car.
if defined DEMO echo  Demo: a simulated car. Press the Demo button on the page to start it.
if not defined DEMO echo  Adapter port: %ST_PORT%    Protocol: %PROTO%  [0 = automatic]
if defined PHONE echo  Phone: a phone on the same Wi-Fi can open the PHONE LINK printed below.
if defined PHONE echo  Anyone on this Wi-Fi who has that full link can watch the live data,
if defined PHONE echo  so use this only on your own Wi-Fi or your phone's hotspot.
if defined PHONE echo  If Windows asks about the firewall, allow it on Private networks.
if not defined PHONE echo  To use a phone too, close this and double-click "Shadetree with phone".
echo.
echo  Leave this window open. Close it to stop.
echo ==========================================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Shadetree'; $null = New-Item -ItemType Directory -Force -Path $d; Write-Host (' Runs are saved in ' + $d + ' (they can contain the VIN: keep them private)'); $q = [char]34; $i = New-Object System.Diagnostics.ProcessStartInfo; $i.FileName = $env:ST_EXE; $i.Arguments = $env:ST_ARGS + ' --out-dir ' + $q + $d + $q; $i.WorkingDirectory = $d; $i.UseShellExecute = $false; $i.RedirectStandardOutput = $true; $p = [System.Diagnostics.Process]::Start($i); while ($null -ne ($l = $p.StandardOutput.ReadLine())) { Write-Host $l; if ($l.StartsWith('console: http')) { Start-Process $l.Substring(9); Write-Host ' Opened the console in your web browser. If it did not open, copy the link above into the browser.' } elseif ($l.StartsWith('console (other devices): http')) { $u = $l.Substring(25); $c = ''; try { Set-Clipboard -Value $u; $c = ' [copied: paste it into a text or e-mail to your phone]' } catch { }; Write-Host ''; Write-Host (' PHONE LINK' + $c + ':'); Write-Host ('   ' + $u); Write-Host ' On the phone it opens in the Handheld view.' } }; $p.WaitForExit()"
echo.
echo Shadetree has stopped. If you see an error above, the guide's troubleshooting table explains it.
goto done

:notinstalled
echo Shadetree is not installed yet, or the install is incomplete.
echo Run install-windows.ps1 first: right-click it, then "Run with PowerShell".

:done
echo.
pause

:end
endlocal
