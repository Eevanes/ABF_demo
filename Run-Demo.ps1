param(
    [ValidateSet('demo','mcp-walkthrough','selftest','serve','serve-staff','workbuddy-poc','doctor-v03','doctor-v04','v04-submission-check','reconcile','verify','live','connect-wecom','connect-model','provision-wecom')]
    [string]$Mode = 'demo',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$arenaPriorPythonPath = $env:PYTHONPATH
$arenaBootstrapPath = Join-Path $PSScriptRoot 'scripts/python_bootstrap'
$env:PYTHONPATH = if ($arenaPriorPythonPath) { "$arenaBootstrapPath$([IO.Path]::PathSeparator)$arenaPriorPythonPath" } else { $arenaBootstrapPath }
$arenaPocPriorEnvironment = @{}
if ($Mode -eq 'workbuddy-poc') {
    if (-not $PSBoundParameters.ContainsKey('Port')) { $Port = 8766 }
    $arenaPocEnvironment = @{
        ARENA_REGISTRY = 'smartsheet'
        ARENA_WRITER = 'local'
        ARENA_STAFF_WRITES_ENABLED = 'false'
        ARENA_SMARTSHEET_WRITES_ENABLED = 'false'
        ARENA_STAFF_CREDENTIALS = '[]'
        ARENA_DATA_DIR = (Join-Path $PSScriptRoot '.arena/workbuddy-poc')
    }
    foreach ($arenaPocName in $arenaPocEnvironment.Keys) {
        $arenaPocPriorEnvironment[$arenaPocName] = [Environment]::GetEnvironmentVariable($arenaPocName, 'Process')
        [Environment]::SetEnvironmentVariable($arenaPocName, $arenaPocEnvironment[$arenaPocName], 'Process')
    }
}
$taskWorkspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if ((Split-Path (Split-Path $PSScriptRoot -Parent) -Leaf) -eq 'outputs') {
    $taskWorkDir = Join-Path $taskWorkspace 'work'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $taskWorkDir 'arena-venv'
    $env:UV_CACHE_DIR = Join-Path $taskWorkDir 'uv-cache'
    if (-not $env:ARENA_DATA_DIR) {
        $env:ARENA_DATA_DIR = Join-Path $taskWorkDir 'arena-demo-data'
    }
}
try { switch ($Mode) {
    'mcp-walkthrough' { & uv run --frozen python scripts/mcp_walkthrough.py }
    'v04-submission-check' { & uv run --frozen python scripts/v04_submission_acceptance.py }
    'serve' { & uv run --frozen arena serve --port $Port }
    'serve-staff' { & uv run --frozen arena serve-staff --port $Port }
    'workbuddy-poc' { & uv run --frozen arena serve-staff --port $Port }
    'verify' {
        & uv run --frozen pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
        & uv run --frozen ruff check .
        if ($LASTEXITCODE -ne 0) { throw 'ruff failed' }
        & uv run --frozen mypy src
    }
    'live' { & uv run --frozen arena serve --port $Port --with-bot --with-cloud --allow-offline }
    default { & uv run --frozen arena $Mode }
}
if ($LASTEXITCODE -ne 0) { throw "Arena 命令失败，退出码 $LASTEXITCODE" }
} finally {
    $env:PYTHONPATH = $arenaPriorPythonPath
    foreach ($arenaPocName in $arenaPocPriorEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($arenaPocName, $arenaPocPriorEnvironment[$arenaPocName], 'Process')
    }
}
