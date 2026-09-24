[CmdletBinding()]
param([string]$Python312 = '', [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Executable $($Arguments -join ' ')" }
}

$candidates = @()
if ($Python312) { $candidates += $Python312 }
$candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$candidates += "$env:ProgramFiles\Python312\python.exe"
$candidates += (Join-Path $PSScriptRoot '.venv312\Scripts\python.exe')
$found = Get-Command python.exe -ErrorAction SilentlyContinue
if ($found) { $candidates += $found.Source }
$base = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    try {
        $raw = & $candidate -c "import sys,struct,json; print(json.dumps(dict(version=list(sys.version_info[:2]),bits=struct.calcsize('P')*8,base=sys._base_executable)))" 2>$null
        if ($LASTEXITCODE -ne 0) { continue }
        $info = ($raw -join '') | ConvertFrom-Json
        if ($info.version[0] -eq 3 -and $info.version[1] -eq 12 -and $info.bits -eq 64) {
            $base = $info.base
            break
        }
    } catch { continue }
}
if (-not $base) {
    throw 'Python 3.12 x64 not found. Install it, or run: .\Setup-WakeGuard.ps1 -Python312 "C:\path\to\python.exe". Existing environments were not deleted.'
}
Write-Host "Using base interpreter: $base"
Write-Host 'Creating isolated environments; old .venv / .venv312 are left untouched.'
foreach ($envName in @('.venv_wakeguard', '.venv_phone')) {
    $target = Join-Path $PSScriptRoot $envName
    $exe = Join-Path $target 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $exe)) { Invoke-Checked $base @('-m', 'venv', $target) }
    Invoke-Checked $exe @('-c', "import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8, 'Use a Python 3.12 x64 environment'")
    Invoke-Checked $exe @('-m', 'pip', 'install', '--upgrade', 'pip')
    $requirements = if ($envName -eq '.venv_phone') { 'requirements_phone.txt' } else { 'requirements.txt' }
    Invoke-Checked $exe @('-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot $requirements))
    Invoke-Checked $exe @('-m', 'pip', 'check')
}
$vision = Join-Path $PSScriptRoot '.venv_wakeguard\Scripts\python.exe'
$phone = Join-Path $PSScriptRoot '.venv_phone\Scripts\python.exe'
Invoke-Checked $vision @('scripts\doctor.py')
Invoke-Checked $phone @('-c', "import importlib.metadata,pyicloud; print('Phone import:',importlib.metadata.version('pyicloud'))")
if (-not $SkipTests) { Invoke-Checked $vision @('-m', 'unittest', 'discover', '-s', 'tests', '-v') }
Write-Host ''
Write-Host 'Setup checks completed. Double-click Start-WakeGuard.cmd.'
Write-Host 'First run: Preview, Test speech, Calibrate, Verify setup, Connect/test phone, START.'
Write-Host 'No camera capture, Apple login or actual phone sound was performed during setup.'
