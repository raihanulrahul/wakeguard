# App-local setup. No Windows Python installer, global pip, PATH edit or registration.
[CmdletBinding()]
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if (-not [Environment]::Is64BitOperatingSystem) { throw 'WakeGuard requires 64-bit Windows.' }
$root = [IO.Path]::GetFullPath($PSScriptRoot)
if (-not (Test-Path -LiteralPath (Join-Path $root 'wakeguard\app.py'))) {
    throw 'Run this file from the WakeGuard repository, not a user profile directory.'
}

function Invoke-CheckedPrivate {
    param([string]$Exe, [string[]]$ArgsList)
    & $Exe @ArgsList
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Exe" }
}

function Assert-OrdinaryPath {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing a junction/symbolic-link path: $current"
            }
        }
        $parent = Split-Path -Path $current -Parent
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
}

function Get-PythonSafetySnapshot {
    $rows = @()
    foreach ($base in @('HKCU:\Software\Python', 'HKLM:\Software\Python',
                        'HKLM:\Software\WOW6432Node\Python',
                        'HKCU:\Software\Classes\.py', 'HKCU:\Software\Classes\.pyw',
                        'HKLM:\Software\Classes\.py', 'HKLM:\Software\Classes\.pyw',
                        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.py\UserChoice',
                        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pyw\UserChoice')) {
        if (Test-Path -LiteralPath $base) {
            $keys = @(Get-Item -LiteralPath $base)
            $keys += @(Get-ChildItem -LiteralPath $base -Recurse -ErrorAction Stop)
            foreach ($key in $keys) {
                foreach ($name in @($key.GetValueNames() | Sort-Object)) {
                    $rows += [ordered]@{key=$key.Name; name=$name; value=$key.GetValue($name)}
                }
            }
        }
    }
    $commands = @(Get-Command python.exe, python3.exe, pip.exe, py.exe -CommandType Application -All -ErrorAction SilentlyContinue |
        Sort-Object Name, Source | ForEach-Object { [ordered]@{name=$_.Name; source=$_.Source} })
    [ordered]@{
        processPath=$env:PATH
        userPath=[Environment]::GetEnvironmentVariable('PATH','User')
        machinePath=[Environment]::GetEnvironmentVariable('PATH','Machine')
        processPathExt=$env:PATHEXT
        userPathExt=[Environment]::GetEnvironmentVariable('PATHEXT','User')
        machinePathExt=[Environment]::GetEnvironmentVariable('PATHEXT','Machine')
        commands=$commands
        registrations=$rows
    } | ConvertTo-Json -Depth 12 -Compress
}

Assert-OrdinaryPath $root
$bootstrap = Join-Path $root '.bootstrap'
$runtime = Join-Path $root '.runtime'
foreach ($path in @($bootstrap, $runtime, (Join-Path $root '.venv_wakeguard'), (Join-Path $root '.venv_phone'))) {
    Assert-OrdinaryPath $path
}
$before = Get-PythonSafetySnapshot
$oldLocation = Get-Location
$envPattern = '^(UV_|PIP_|PYTHON|VIRTUAL_ENV$|TCL_LIBRARY$|TK_LIBRARY$|TEMP$|TMP$)'
$savedEnv = @{}
Get-ChildItem Env: | Where-Object { $_.Name -match $envPattern } | ForEach-Object { $savedEnv[$_.Name] = $_.Value }
$oldTls = [Net.ServicePointManager]::SecurityProtocol
$oldProgress = $ProgressPreference
try {
    New-Item -ItemType Directory -Path $bootstrap -Force | Out-Null
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $before | Set-Content -LiteralPath (Join-Path $bootstrap 'safety-before.json') -Encoding UTF8
    # Only this setup process is changed. Do not inherit another project's pip target/config.
    Get-ChildItem Env: | Where-Object { $_.Name -match $envPattern } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
    $tempDir = Join-Path $bootstrap 'temp'
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $env:TEMP = $tempDir
    $env:TMP = $tempDir
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PIP_CONFIG_FILE = 'NUL'
    $env:PIP_CACHE_DIR = Join-Path $bootstrap 'pip-cache'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:UV_PYTHON_INSTALL_DIR = $runtime
    $env:UV_CACHE_DIR = Join-Path $bootstrap 'uv-cache'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    $env:UV_PYTHON_INSTALL_REGISTRY = '0'
    $env:UV_NO_CONFIG = '1'
    Set-Location -LiteralPath $root
    [Net.ServicePointManager]::SecurityProtocol = $oldTls -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    $uvVersion = '0.12.19'
    $archive = Join-Path $bootstrap "uv-$uvVersion-windows-x64.zip"
    $expected = '6dbb02d79e419522f1c500f0adb1cddcff0cda7d59b0d66ea7f5e3b4a1b2f5f0'
    if (-not (Test-Path -LiteralPath $archive)) {
        $partial = $archive + '.download'
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $partial
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
            throw 'uv archive checksum mismatch. Nothing was executed.'
        }
        Move-Item -LiteralPath $partial -Destination $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'Cached uv archive failed its pinned checksum; stopping without executing it.'
    }
    # Fresh extraction from the verified archive; never run a global uv installation.
    $toolDir = Join-Path $bootstrap ('uv-' + [Guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $archive -DestinationPath $toolDir
    $tools = @(Get-ChildItem -LiteralPath $toolDir -Filter uv.exe -Recurse -File)
    if ($tools.Count -ne 1) { throw 'Expected one uv.exe in the verified archive.' }
    $uv = $tools[0].FullName
    Write-Host 'Downloading an app-private CPython runtime. Existing Python installations are not used or changed.'
    Invoke-CheckedPrivate $uv @('python','install','cpython-3.12.10-windows-x86_64-none',
        '--no-bin','--no-registry','--no-config','--install-dir',$runtime,'--cache-dir',$env:UV_CACHE_DIR)
    $privatePython = Join-Path $runtime 'cpython-3.12.10-windows-x86_64-none\python.exe'
    if (-not (Test-Path -LiteralPath $privatePython)) { throw 'Private Python was not found at the expected location.' }
    Assert-OrdinaryPath $privatePython
    Invoke-CheckedPrivate $privatePython @('-I','-B','-c',
        "import sys,struct,ssl,venv,ensurepip,tkinter; assert sys.version_info[:3]==(3,12,10) and struct.calcsize('P')==8; r=tkinter.Tk(); r.withdraw(); r.update(); r.destroy(); print('Private Python 3.12.10 x64 and Tcl/Tk passed')")
    # Refuse to repurpose an environment whose base interpreter is somewhere else.
    foreach ($name in @('.venv_wakeguard','.venv_phone')) {
        $target = Join-Path $root $name
        if (Test-Path -LiteralPath $target) {
            $exe = Join-Path $target 'Scripts\python.exe'
            if (-not (Test-Path -LiteralPath $exe)) { throw "Incomplete environment at $target. No automatic deletion was attempted." }
            $check = "import sys,os; n=lambda p:os.path.normcase(os.path.realpath(p)); assert sys.prefix!=sys.base_prefix and n(sys.prefix)==n(sys.argv[1]) and n(sys._base_executable)==n(sys.argv[2]), 'Existing environment uses another Python; stopping without changing it'"
            Invoke-CheckedPrivate $exe @('-I','-B','-c',$check,$target,$privatePython)
            $cfg = Get-Content -LiteralPath (Join-Path $target 'pyvenv.cfg') -Raw
            if ($cfg -match '(?im)^include-system-site-packages\s*=\s*true') {
                throw "Environment shares system packages: $target. Not modifying it."
            }
        }
    }
    & (Join-Path $root 'Setup-WakeGuard.ps1') -Python312 $privatePython -SkipTests:$SkipTests
    Write-Host "Private runtime: $privatePython"
} finally {
    Get-ChildItem Env: | Where-Object { $_.Name -match $envPattern } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
    foreach ($name in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnv[$name], 'Process') }
    [Net.ServicePointManager]::SecurityProtocol = $oldTls
    $ProgressPreference = $oldProgress
    Set-Location -LiteralPath $oldLocation.Path
    $after = Get-PythonSafetySnapshot
    if (Test-Path -LiteralPath $bootstrap) {
        $after | Set-Content -LiteralPath (Join-Path $bootstrap 'safety-after.json') -Encoding UTF8
    }
    if ($before -cne $after) {
        throw 'Python command/PATH/registration snapshot changed during setup. Inspect .bootstrap\safety-*.json; no automatic rollback was attempted.'
    }
    Write-Host 'PASS: existing python/pip/py command paths, PATH/PATHEXT and inspected Python/file-association registration values unchanged.'
}
