# Shadetree installer for Windows (no Claude needed). Read-only OBD-II console.
#
# Run it: right-click this file, then "Run with PowerShell".
# Or, in a Command Prompt or PowerShell window:
#   powershell -ExecutionPolicy Bypass -File "%USERPROFILE%\Downloads\install-windows.ps1"
#
# What it does (no administrator rights needed; running it again updates everything):
#   1. Finds Python 3.11 or newer, or installs Python 3.12 for you only.
#   2. Installs shadetree-ai into its own folder: %LOCALAPPDATA%\Shadetree
#   3. Makes the data folder Documents\Shadetree (your runs go there).
#   4. Looks for the OBDLink adapter's COM port and remembers it.
#   5. Puts "Shadetree", "Shadetree demo (no car)" and "Shadetree with phone" on the Desktop.
#
# -Source   where to install shadetree-ai from: a URL, a .zip file or a folder (default: GitHub main).
# -FindPort only look for the adapter and save its port (the launcher uses this); -Port COM5 saves that port.
# Not yet run on a Windows machine: written and reviewed on Linux only.

param(
    [string]$Source = 'https://github.com/iamneilroberts/shadetree-ai/archive/refs/heads/main.zip',
    [switch]$FindPort,
    [string]$Port = '',
    [switch]$NoPause
)

$AppDir = Join-Path $env:LOCALAPPDATA 'Shadetree'
$PortFile = Join-Path $AppDir 'port.txt'
$PythonVersion = '3.12.10'   # the last 3.12 release with a Windows installer on python.org

function Say([string]$text) { Write-Host $text }
function Step([string]$text) { Write-Host ''; Write-Host $text -ForegroundColor Cyan }

function Get-ComPorts {
    # Every COM port Windows can see right now, with a score: 2 = looks like an OBDLink/STN, 1 = an FTDI USB serial chip.
    $ports = @()
    try { $pnp = @(Get-CimInstance -ClassName Win32_PnPEntity -ErrorAction Stop | Where-Object { $_.Name -match '\(COM\d+\)' }) } catch { $pnp = @() }
    foreach ($d in $pnp) {
        if ($d.Name -match '\((COM\d+)\)') {
            $ports += [pscustomobject]@{ Port = $Matches[1]; Name = $d.Name; Text = "$($d.Name) $($d.Description) $($d.Manufacturer) $($d.PNPDeviceID)" }
        }
    }
    try { $ser = @(Get-CimInstance -ClassName Win32_SerialPort -ErrorAction Stop) } catch { $ser = @() }
    foreach ($s in $ser) {
        if ($s.DeviceID -match '^COM\d+$' -and -not ($ports | Where-Object { $_.Port -eq $s.DeviceID })) {
            $ports += [pscustomobject]@{ Port = $s.DeviceID; Name = "$($s.Name) ($($s.DeviceID))"; Text = "$($s.Name) $($s.Description) $($s.PNPDeviceID)" }
        }
    }
    foreach ($p in $ports) {
        $score = 0
        if ($p.Text -match 'OBDLink|ScanTool|STN\d|ELM327') { $score = 2 } elseif ($p.Text -match 'FTDI|VID_0403') { $score = 1 }
        $p | Add-Member -NotePropertyName Score -NotePropertyValue $score
    }
    return $ports
}

function Save-Port([string]$com) {
    $null = New-Item -ItemType Directory -Force -Path $AppDir
    Set-Content -LiteralPath $PortFile -Value $com -Encoding ASCII
}

function Find-Adapter {
    # Returns the adapter's COM port (and saves it), or '' when none is found.
    if ($Port) {
        if ($Port -notmatch '^COM\d+$') { Say "  '$Port' is not a COM port name such as COM3."; return '' }
        Save-Port $Port.ToUpper()
        Say "  Using $($Port.ToUpper()) (you chose it; it is remembered)."
        return $Port.ToUpper()
    }
    $ports = @(Get-ComPorts)
    $best = @($ports | Where-Object { $_.Score -gt 0 } | Sort-Object -Property @{Expression = 'Score'; Descending = $true}, Port)
    if ($best.Count -gt 0) {
        Save-Port $best[0].Port
        Say "  Found the adapter: $($best[0].Name)"
        if ($best.Count -gt 1) { Say "  (Other possible ports: $(($best | Select-Object -Skip 1 | ForEach-Object { $_.Port }) -join ', '). If $($best[0].Port) is wrong, see the guide.)" }
        return $best[0].Port
    }
    if (Test-Path -LiteralPath $PortFile) {
        $saved = (Get-Content -LiteralPath $PortFile -TotalCount 1).Trim()
        if ($ports | Where-Object { $_.Port -eq $saved }) { Say "  Using the saved port $saved."; return $saved }
    }
    Say '  No OBDLink adapter found. Is it plugged into the laptop with its USB cable?'
    if ($ports.Count -gt 0) {
        Say '  Ports Windows can see right now:'
        foreach ($p in $ports) { Say "    $($p.Name)" }
        Say '  If one of these is the adapter, start Shadetree with that port once, for example:'
        Say '    shadetree-start.bat COM5'
    }
    return ''
}

if ($FindPort) {
    $found = Find-Adapter
    if ($found) { exit 0 } else { exit 1 }
}

function Wait-Close {
    if (-not $NoPause) { Write-Host ''; Read-Host 'Press Enter to close this window' | Out-Null }
}

function Find-Python {
    # The full path of a Python 3.11+ (not the Microsoft Store one), or ''.
    $code = 'import sys;print(sys.executable if sys.version_info[:2]>=(3,11) else 0)'
    $tries = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $tries += , @('py', '-3') }
    if (Get-Command python -ErrorAction SilentlyContinue) { $tries += , @('python') }
    $known = @()
    $known += @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') -ErrorAction SilentlyContinue)
    $known += @(Get-ChildItem -Path (Join-Path $env:ProgramFiles 'Python3*\python.exe') -ErrorAction SilentlyContinue)
    foreach ($k in ($known | Sort-Object -Property FullName -Descending)) { $tries += , @($k.FullName) }
    foreach ($t in $tries) {
        try {
            $cmd = $t[0]; $rest = @($t | Select-Object -Skip 1)
            $out = & $cmd @rest -c $code 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $exe = "$out".Trim()
                if ($exe -ne '0' -and $exe -notmatch 'WindowsApps' -and (Test-Path -LiteralPath $exe)) { return $exe }
            }
        } catch { }
    }
    return ''
}

function Install-Python {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say '  Installing Python 3.12 with winget (for you only; this can take a few minutes)...'
        & winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
        $py = Find-Python
        if ($py) { return $py }
        Say '  winget did not finish the job; downloading Python from python.org instead.'
    }
    $suffix = '-amd64'
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $suffix = '-arm64' } elseif (-not [Environment]::Is64BitOperatingSystem) { $suffix = '' }
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion$suffix.exe"
    $file = Join-Path $env:TEMP "python-$PythonVersion$suffix.exe"
    Say "  Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing -ErrorAction Stop
    $sig = Get-AuthenticodeSignature -FilePath $file
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw "the downloaded Python installer is not signed by the Python Software Foundation ($($sig.Status)); it was not run"
    }
    Say '  Installing Python for you only (no administrator needed; a few minutes)...'
    $p = Start-Process -FilePath $file -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'InstallLauncherAllUsers=0', 'Include_test=0' -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "the Python installer stopped with code $($p.ExitCode)" }
    return Find-Python
}

function Get-InstallFile([string]$pkg, [string]$name) {
    # install\<name> from the package being installed (newest), else the copy next to this script; $null if neither.
    if (Test-Path -LiteralPath $pkg -PathType Container) {
        $f = Join-Path $pkg "install\$name"
        if (Test-Path -LiteralPath $f) { return [IO.File]::ReadAllText($f) }
    } elseif ($pkg -like '*.zip') {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($pkg)
        try {
            $entry = $zip.Entries | Where-Object { $_.FullName -like "*install/$name" } | Select-Object -First 1
            if ($entry) {
                $reader = New-Object IO.StreamReader($entry.Open())
                try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
            }
        } finally { $zip.Dispose() }
    }
    $f = Join-Path $PSScriptRoot $name
    if (Test-Path -LiteralPath $f) { return [IO.File]::ReadAllText($f) }
    return $null
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'   # much faster downloads in Windows PowerShell 5.1

    Say 'Shadetree installer. It only reads from the car: it never clears codes or changes anything.'

    Step 'Step 1 of 5: Python'
    $py = Find-Python
    if ($py) { Say "  Found Python: $py" } else {
        Say '  Python 3.11 or newer is not installed yet.'
        $py = Install-Python
        if (-not $py) { throw 'Python was installed but cannot be found yet. Close this window and run the installer again.' }
        Say "  Python is ready: $py"
    }

    Step 'Step 2 of 5: the Shadetree program'
    while (Get-Process -Name 'shadetree-ai' -ErrorAction SilentlyContinue) {
        # Windows locks a running program's files, so the update would fail
        Say '  Shadetree is still running. Close its black window, then press Enter here.'
        $null = Read-Host
    }
    $null = New-Item -ItemType Directory -Force -Path $AppDir
    $venv = Join-Path $AppDir 'venv'
    $vpy = Join-Path $venv 'Scripts\python.exe'
    if (Test-Path -LiteralPath $vpy) {
        $ok = $false
        try { & $vpy -c 'import sys' 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch { }
        if (-not $ok) { Say '  The old program folder is broken; making a new one.'; Remove-Item -LiteralPath $venv -Recurse -Force }
    }
    if (-not (Test-Path -LiteralPath $vpy)) {
        & $py -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $vpy)) { throw "could not make the program folder $venv" }
    }
    if ($Source -match '^https?://') {
        $pkg = Join-Path $env:TEMP 'shadetree-ai-download.zip'
        Say "  Downloading the latest version from $Source"
        Remove-Item -LiteralPath $pkg -Force -ErrorAction SilentlyContinue   # never install an old download
        Invoke-WebRequest -Uri $Source -OutFile $pkg -UseBasicParsing -ErrorAction Stop
    } elseif (Test-Path -LiteralPath $Source) {
        $pkg = (Resolve-Path -LiteralPath $Source).Path
    } else {
        throw "cannot find the source $Source"
    }
    Say '  Installing shadetree-ai and what it needs (a minute or two)...'
    & $vpy -m pip install --disable-pip-version-check --upgrade $pkg
    if ($LASTEXITCODE -ne 0) { throw 'pip could not install shadetree-ai (see the messages above)' }
    & $vpy -m pip install --disable-pip-version-check --force-reinstall --no-deps $pkg   # same version number, newer code: always replace it
    if ($LASTEXITCODE -ne 0) { throw 'pip could not update shadetree-ai (see the messages above)' }
    if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\shadetree-ai.exe'))) { throw 'shadetree-ai.exe is missing after the install' }
    $bat = Join-Path $AppDir 'shadetree-start.bat'
    $text = Get-InstallFile $pkg 'shadetree-start.bat'
    if (-not $text) { throw 'cannot find shadetree-start.bat: keep it in the same folder as install-windows.ps1' }
    [IO.File]::WriteAllText($bat, ($text -replace "`r?`n", "`r`n"), [Text.Encoding]::ASCII)   # a batch file needs Windows line endings
    # the installer itself, newest first, so the Update shortcut and the launcher's port search run the latest copy
    $self = Join-Path $AppDir 'install-windows.ps1'
    $mine = Get-InstallFile $pkg 'install-windows.ps1'
    if ($mine) { [IO.File]::WriteAllText($self, $mine, [Text.Encoding]::ASCII) }
    elseif ($PSCommandPath -and ($PSCommandPath -ne $self)) { Copy-Item -LiteralPath $PSCommandPath -Destination $self -Force }
    if (Test-Path -LiteralPath $self) { Unblock-File -LiteralPath $self }
    Say "  Installed in $AppDir"

    Step 'Step 3 of 5: the data folder'
    $data = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Shadetree'
    $null = New-Item -ItemType Directory -Force -Path $data
    $note = Join-Path $data 'READ ME - private.txt'
    if (-not (Test-Path -LiteralPath $note)) {
        Set-Content -LiteralPath $note -Encoding ASCII -Value @(
            'Shadetree saves runs (runs\), raw adapter transcripts (transcripts\) and car profiles here.',
            'Transcripts can contain your car''s VIN. Keep this folder private; do not post its files online.')
    }
    Say "  Your runs will be saved in $data"
    Say '  They can contain the car''s VIN (its serial number): keep them private.'

    Step 'Step 4 of 5: the OBDLink adapter'
    $found = Find-Adapter
    if (-not $found) { Say '  That is fine: plug it in later. Shadetree looks for it every time it starts.' }

    Step 'Step 5 of 5: Desktop shortcuts'
    $desk = [Environment]::GetFolderPath('Desktop')
    $shell = New-Object -ComObject WScript.Shell
    $links = @(
        @('Shadetree', '', 'Start the Shadetree console with the OBDLink adapter (read-only)'),
        @('Shadetree demo (no car)', 'demo', 'Start the Shadetree console with a simulated car'),
        @('Shadetree with phone', 'phone', 'Start the Shadetree console and let a phone on the same Wi-Fi open it')
    )
    foreach ($l in $links) {
        $lnk = Join-Path $desk ($l[0] + '.lnk')
        $keep = Test-Path -LiteralPath $lnk   # keep words added to an existing shortcut's Target, such as a protocol number
        $s = $shell.CreateShortcut($lnk)
        $s.TargetPath = $bat
        if (-not $keep) { $s.Arguments = $l[1] }
        $s.WorkingDirectory = $AppDir
        $s.Description = $l[2]
        $s.Save()
        Say "  $($l[0])"
    }
    $s = $shell.CreateShortcut((Join-Path $desk 'Update Shadetree.lnk'))
    $s.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$self`""
    $s.WorkingDirectory = $AppDir
    $s.Description = 'Download and install the latest Shadetree (safe to run any time)'
    $s.Save()
    Say '  Update Shadetree'

    Write-Host ''
    Write-Host 'All done. Turn the ignition on, then double-click "Shadetree" on your Desktop.' -ForegroundColor Green
    Write-Host 'No car nearby? Double-click "Shadetree demo (no car)" to try it.'
    Wait-Close
    exit 0
} catch {
    Write-Host ''
    Write-Host "Something went wrong: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'What to try:'
    Write-Host '  - Check the internet connection, then run the installer again (it is safe to repeat).'
    Write-Host '  - Restart the laptop if Python was just installed, then run it again.'
    Write-Host '  - Still stuck? Send Neil a photo of this window.'
    Wait-Close
    exit 1
}
