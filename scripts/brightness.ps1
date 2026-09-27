# Local WMI only. No power-plan, registry, gamma, driver or admin changes.
[CmdletBinding()]
param([ValidateSet('list','read','write')][string]$Operation = 'list')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    $items = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness -ErrorAction Stop |
        Where-Object { $_.Active })
    if ($Operation -eq 'list') {
        $rows = @($items | ForEach-Object { @{id=$_.InstanceName; value=[int]$_.CurrentBrightness; maximum=100} })
        [Console]::WriteLine((ConvertTo-Json -InputObject $rows -Compress -Depth 4))
        exit 0
    }
    $inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $matches = @($items | Where-Object { $_.InstanceName -ceq [string]$inputData.id })
    if ($matches.Count -ne 1) { throw 'Exact brightness device is unavailable' }
    if ($Operation -eq 'write') {
        $value = [int]$inputData.value
        if ($value -lt 0 -or $value -gt 100) { throw 'Invalid brightness value' }
        $methods = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop |
            Where-Object { $_.Active -and $_.InstanceName -ceq [string]$inputData.id })
        if ($methods.Count -ne 1) { throw 'Exact brightness control is unavailable' }
        $result = Invoke-CimMethod -InputObject $methods[0] -MethodName WmiSetBrightness `
            -Arguments @{Timeout=[uint32]0; Brightness=[byte]$value} -ErrorAction Stop
        if ($result.ReturnValue -ne 0) { throw 'Brightness change was not accepted' }
        $matches = @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness -ErrorAction Stop |
            Where-Object { $_.Active -and $_.InstanceName -ceq [string]$inputData.id })
        if ($matches.Count -ne 1) { throw 'Brightness readback unavailable' }
    }
    [Console]::WriteLine((@{value=[int]$matches[0].CurrentBrightness; maximum=100} | ConvertTo-Json -Compress))
} catch {
    [Console]::WriteLine('{"error":"WMI brightness unavailable or access denied"}')
    exit 1
}
