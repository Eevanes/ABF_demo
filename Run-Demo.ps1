param(
    [ValidateSet('demo','mcp-walkthrough','selftest','serve','live','connect-wecom','connect-model','provision-wecom')]
    [string]$Mode = 'demo',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskWorkspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if ((Split-Path (Split-Path $PSScriptRoot -Parent) -Leaf) -eq 'outputs') {
    $taskWorkDir = Join-Path $taskWorkspace 'work'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $taskWorkDir 'arena-venv'
    $env:UV_CACHE_DIR = Join-Path $taskWorkDir 'uv-cache'
    if (-not $env:ARENA_DATA_DIR) {
        $env:ARENA_DATA_DIR = Join-Path $taskWorkDir 'arena-demo-data'
    }
}
switch ($Mode) {
    'mcp-walkthrough' { & uv run --frozen python scripts/mcp_walkthrough.py }
    'serve' { & uv run --frozen arena serve --port $Port }
    'live' { & uv run --frozen arena serve --port $Port --with-bot --with-cloud --allow-offline }
    default { & uv run --frozen arena $Mode }
}
if ($LASTEXITCODE -ne 0) { throw "Arena 命令失败，退出码 $LASTEXITCODE" }
