param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:PYTHONUTF8 = '1'
    $selectedPython = $null
    $pythonPrefix = @()
    $candidates = @('.\.venv\Scripts\python.exe', 'python', 'py')
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        $candidatePrefix = @()
        if ($candidate -eq 'py') { $candidatePrefix = @('-3') }
        try {
            & $candidate @candidatePrefix -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $selectedPython = $candidate
                $pythonPrefix = $candidatePrefix
                break
            }
        } catch {}
    }
    if (-not $selectedPython) { throw 'Python 3.11+ is required. Install Python with Add to PATH, then reopen this launcher.' }
    $launchArgs = @('-m', 'scripts.launch', '--port', "$Port")
    if ($NoBrowser) { $launchArgs += '--no-browser' }
    & $selectedPython @pythonPrefix @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "Memory Guard exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
