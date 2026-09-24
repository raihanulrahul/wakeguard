# Optional OFFLINE Windows grammar recognition. No recording or network API.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$recognizer = $null
try {
    Add-Type -AssemblyName System.Speech
    $installed = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Where-Object { $_.Culture.Name -like 'en-*' })
    if ($installed.Count -eq 0) { throw 'No installed English recognizer' }
    $recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::new($installed[0])
    $choices = [System.Speech.Recognition.Choices]::new()
    $choices.Add([string[]]@('wakeguard ready', 'wakeguard next', 'wakeguard repeat', 'wakeguard back', 'wakeguard stop', 'wake guard ready', 'wake guard next', 'wake guard repeat', 'wake guard back', 'wake guard stop'))
    $builder = [System.Speech.Recognition.GrammarBuilder]::new()
    $builder.Culture = $recognizer.RecognizerInfo.Culture
    $builder.Append($choices)
    $grammar = [System.Speech.Recognition.Grammar]::new($builder)
    $recognizer.LoadGrammar($grammar)
    $recognizer.SetInputToDefaultAudioDevice()
    Register-ObjectEvent -InputObject $recognizer -EventName SpeechRecognized -SourceIdentifier 'WakeGuardSpeech' | Out-Null
    $recognizer.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
    [Console]::WriteLine('{"event":"voice_ready"}')
    while ($true) {
        $event = Wait-Event -SourceIdentifier 'WakeGuardSpeech' -Timeout 1
        if ($null -ne $event) {
            $result = $event.SourceEventArgs.Result
            if ($result.Confidence -ge 0.75) {
                $payload = @{event='command'; text=$result.Text.ToLowerInvariant().Replace('wake guard ', 'wakeguard ')} | ConvertTo-Json -Compress
                [Console]::WriteLine($payload)
            }
            Remove-Event -EventIdentifier $event.EventIdentifier
        }
    }
} catch { [Console]::WriteLine('{"event":"voice_error","message":"Offline voice unavailable; use SPACE / R / B / Escape."}'); exit 1 }
finally {
    Unregister-Event -SourceIdentifier 'WakeGuardSpeech' -ErrorAction SilentlyContinue
    if ($null -ne $recognizer) { $recognizer.Dispose() }
}
