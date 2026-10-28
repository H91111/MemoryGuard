param(
    [string]$Python = 'python',
    [switch]$Start,
    [int]$Port = 18080
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
& $Python (Join-Path $PSScriptRoot 'setup_local_planner.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned local planner setup failed' }
$runtimeDir = Join-Path $workspace 'runtime\llama-cpp'
$serverPath = Join-Path $runtimeDir 'b11951\llama-server.exe'
& $serverPath --version
if ($LASTEXITCODE -ne 0) { throw 'llama-server --version failed' }

if ($Start) {
    $modelPath = Join-Path $workspace 'models\qwen3-0.6b\Qwen3-0.6B-Q8_0.gguf'
    $serverArgs = @('-m', ('"' + $modelPath + '"'), '--alias', 'qwen3-0.6b-q8_0', '--host', '127.0.0.1', '--port', "$Port", '-c', '4096', '-t', '4', '-np', '1', '--jinja', '-ngl', '0')
    $process = Start-Process -FilePath $serverPath -ArgumentList $serverArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log')
    [ordered]@{ pid = $process.Id; executable = $serverPath; arguments = $serverArgs; url = "http://127.0.0.1:$Port/v1"; started_at = [DateTimeOffset]::Now.ToString('o') } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $runtimeDir 'server.json') -Encoding utf8
    Write-Host "Started local planner PID $($process.Id), http://127.0.0.1:$Port/v1"
}
