# Per-user, selectable-folder installation. No Git, system Python or admin needed.
[CmdletBinding()]
param(
    [string]$Destination = '',
    [string]$SourceRef = 'main',
    [switch]$Update,
    [switch]$NoLaunch,
    [switch]$NoShortcut,
    [string]$ArchivePath = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$projectName = 'raihanulrahul/wakeguard'
$oldLocation = Get-Location
$oldTls = [Net.ServicePointManager]::SecurityProtocol
$oldProgress = $ProgressPreference
$installerLock = $null
$staging = $null

function Assert-LocalFolder([string]$Value) {
    if ($Value -notmatch '^[a-zA-Z]:[\\/]') { throw 'Choose a full local folder path, for example E:\Apps\WakeGuard.' }
    $full = [IO.Path]::GetFullPath($Value).TrimEnd('\')
    if ($full.Length -le 3) { throw 'Choose a dedicated folder, not the root of a drive.' }
    if (-not (Test-Path -LiteralPath ([IO.Path]::GetPathRoot($full)))) { throw 'That drive is not available.' }
    $current = $full
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Not an ordinary local folder: $current"
            }
        }
        $parent = Split-Path -Path $current -Parent
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
    return $full
}

function Join-Safe([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative) -or $Relative -match '(^|[\\/])\.\.([\\/]|$)') { throw 'Invalid package path.' }
    $full = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
    if (-not $full.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Package path escapes its folder.' }
    return $full
}

function Read-Package([string]$File) {
    $meta = Get-Content -LiteralPath $File -Raw | ConvertFrom-Json
    if ($meta.Project -cne $projectName -or $meta.Schema -ne 1 -or -not $meta.Files) { throw 'Unknown existing package. Nothing was overwritten.' }
    return $meta
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'WakeGuard requires 64-bit Windows.' }
    if (-not $Destination) {
        Write-Host ''
        Write-Host 'WakeGuard - private desktop setup' -ForegroundColor Cyan
        Write-Host 'Choose a dedicated folder that you can write to. No administrator permission is requested.'
        Write-Host 'Examples: E:\Apps\WakeGuard  or  D:\Codes\wakeguard'
        $defaultFolder = Join-Path $env:LOCALAPPDATA 'Programs\WakeGuard'
        $answer = Read-Host "Install folder [$defaultFolder]"
        $Destination = if ([string]::IsNullOrWhiteSpace($answer)) { $defaultFolder } else { $answer.Trim().Trim('"') }
    }
    $Destination = Assert-LocalFolder ([Environment]::ExpandEnvironmentVariables($Destination))
    $metaPath = Join-Path $Destination '.wakeguard-package.json'
    $previous = $null
    if (Test-Path -LiteralPath (Join-Path $Destination '.git')) {
        throw 'This is an existing Git checkout. Keep it intact: use git pull --ff-only there, or choose a NEW empty folder for this package.'
    }
    if (Test-Path -LiteralPath $Destination) {
        if ($Update) {
            if (-not (Test-Path -LiteralPath $metaPath)) { throw 'This folder was not installed by the package installer. Nothing was overwritten.' }
            $previous = Read-Package $metaPath
            foreach ($file in $previous.Files) {
                $existing = Join-Safe $Destination ([string]$file.Path)
                if (-not (Test-Path -LiteralPath $existing) -or
                    (Get-FileHash -LiteralPath $existing -Algorithm SHA256).Hash -ine [string]$file.Sha256) {
                    throw "Locally edited/missing source: $($file.Path). Preserve your changes before updating."
                }
            }
        } elseif (@(Get-ChildItem -LiteralPath $Destination -Force).Count -gt 0) {
            throw 'The chosen folder is not empty. Choose a new folder, or use Update-WakeGuard.cmd for an existing packaged installation.'
        }
    } elseif ($Update) {
        throw 'Update target does not exist. Run a new install instead.'
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $probe = Join-Path $Destination ('.write-test-' + [guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText($probe, 'WakeGuard write permission test')
    Remove-Item -LiteralPath $probe
    $bootstrap = Join-Path $Destination '.bootstrap'
    New-Item -ItemType Directory -Path $bootstrap -Force | Out-Null
    try {
        $installerLock = [IO.File]::Open((Join-Path $bootstrap 'wakeguard-running.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch { throw 'Close WakeGuard before installing/updating this folder. No processes were killed.' }
    [Net.ServicePointManager]::SecurityProtocol = $oldTls -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    if ($SourceRef -match '^[a-fA-F0-9]{40}$') { $commit = $SourceRef.ToLowerInvariant() }
    else {
        $ref = [Uri]::EscapeDataString($SourceRef)
        $revision = Invoke-RestMethod -Uri "https://api.github.com/repos/$projectName/commits/$ref" -Headers @{ 'User-Agent'='WakeGuard-Installer' }
        $commit = [string]$revision.sha
        if ($commit -notmatch '^[a-f0-9]{40}$') { throw 'Could not resolve an immutable source revision.' }
    }
    Write-Host "Installing to: $Destination"
    Write-Host "Source revision: $commit"
    $staging = Join-Path $bootstrap ('package-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging | Out-Null
    $archive = Join-Path $staging 'source.zip'
    if ($ArchivePath) {
        Copy-Item -LiteralPath ([IO.Path]::GetFullPath($ArchivePath)) -Destination $archive
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$projectName/zip/$commit" -OutFile $archive
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        if ($zip.Entries.Count -gt 2000) { throw 'Unexpectedly large source archive.' }
        foreach ($entry in $zip.Entries) {
            [void](Join-Safe $staging $entry.FullName)
            if ($entry.Length -gt 20000000) { throw 'Unexpectedly large source file.' }
        }
    } finally { $zip.Dispose() }
    $unpacked = Join-Path $staging 'unpacked'
    Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
    $roots = @(Get-ChildItem -LiteralPath $unpacked -Directory)
    if ($roots.Count -ne 1) { throw 'Expected one repository root in source archive.' }
    $source = $roots[0].FullName
    foreach ($essential in @('wakeguard\app.py','Setup-WakeGuard-Private.ps1','Start-WakeGuard.cmd','requirements.txt','Install-WakeGuard.ps1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $essential))) { throw "Source package is missing $essential" }
    }
    $files = @(Get-ChildItem -LiteralPath $source -Recurse -Force -File | ForEach-Object {
        $relative = $_.FullName.Substring($source.Length + 1)
        if ($relative -match '(^|[\\/])(\.runtime|\.bootstrap|\.venv[^\\/]*|\.git)([\\/]|$)' -or $relative -eq '.wakeguard-package.json') {
            throw 'Source archive includes runtime/user files. Stopping.'
        }
        [PSCustomObject]@{ Path=$relative; Sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
    if ($previous) {
        $oldPaths = @($previous.Files | ForEach-Object { $_.Path })
        foreach ($file in $files) {
            $target = Join-Safe $Destination $file.Path
            if ((Test-Path -LiteralPath $target) -and $file.Path -notin $oldPaths) {
                throw "New source conflicts with an unmanaged file: $($file.Path). Nothing was overwritten."
            }
        }
        $backup = Join-Path $bootstrap ('source-backup-' + [guid]::NewGuid().ToString('N'))
        foreach ($file in $previous.Files) {
            $out = Join-Safe $backup $file.Path
            New-Item -ItemType Directory -Path (Split-Path $out -Parent) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Safe $Destination $file.Path) -Destination $out
        }
        Copy-Item -LiteralPath $metaPath -Destination (Join-Path $backup 'package-metadata.json')
        Write-Host "Previous source backed up at: $backup"
    }
    foreach ($file in $files) {
        $out = Join-Safe $Destination $file.Path
        New-Item -ItemType Directory -Path (Split-Path $out -Parent) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Safe $source $file.Path) -Destination $out
    }
    $metadata = @{ Schema=1; Project=$projectName; Revision=$commit; Files=$files; InstalledAt=[DateTime]::UtcNow.ToString('o') }
    $metadata | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
    $privateSetup = Join-Path $Destination 'Setup-WakeGuard-Private.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $privateSetup
    if ($LASTEXITCODE -ne 0) { throw 'Private setup did not finish. Source is retained; rerun Setup-WakeGuard-Private.ps1 from the chosen folder after resolving the error.' }
    if (-not $NoShortcut) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $link = Join-Path $desktop 'WakeGuard.lnk'
        if (Test-Path -LiteralPath $link) {
            $link = Join-Path $desktop ('WakeGuard-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.lnk')
        }
        try {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($link)
            $shortcut.TargetPath = Join-Path $Destination '.venv_wakeguard\Scripts\pythonw.exe'
            $shortcut.Arguments = '-E -s -B "' + (Join-Path $Destination 'wakeguard_launcher.pyw') + '"'
            $shortcut.WorkingDirectory = $Destination
            $shortcut.Description = 'WakeGuard - private desk vigilance assistant'
            $shortcut.Save()
            Write-Host "Desktop shortcut: $link"
        } catch {
            Write-Warning 'Desktop shortcut creation was blocked. Start-WakeGuard.cmd in the selected folder still launches the app.'
        }
    }
    Write-Host ''
    Write-Host 'WakeGuard is installed. No system Python/PATH/launcher registration changes were requested.' -ForegroundColor Green
    Write-Host 'Next: follow the large next-step button. Calibrate this office camera/desk separately.'
    $installerLock.Dispose(); $installerLock = $null
    if (-not $NoLaunch) { & (Join-Path $Destination 'Start-WakeGuard.cmd') }
} finally {
    if ($null -ne $installerLock) { $installerLock.Dispose() }
    [Net.ServicePointManager]::SecurityProtocol = $oldTls
    $ProgressPreference = $oldProgress
    Set-Location -LiteralPath $oldLocation.Path
}
