param([Parameter(Mandatory=$true)][string]$Text)
$ErrorActionPreference = 'Stop'
$synth = $null
try {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SetOutputToDefaultAudioDevice()
    $synth.Rate = 0
    $synth.Volume = 85
    $synth.Speak($Text)
} catch { exit 1 }
finally { if ($null -ne $synth) { $synth.Dispose() } }
exit 0
