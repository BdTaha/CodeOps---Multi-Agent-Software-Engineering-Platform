param([ValidateSet('install', 'build', 'dev')][string]$Action = 'build')
$ErrorActionPreference = 'Stop'
$frontendRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../frontend'))
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$runtimeRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies'
$nodeExecutable = if ($nodeCommand) { $nodeCommand.Source } else { Join-Path $runtimeRoot 'node/bin/node.exe' }
if (-not (Test-Path -LiteralPath $nodeExecutable)) { throw 'Install Node.js 22.12 or newer, then run this script again.' }
$env:PATH = (Split-Path $nodeExecutable) + ';' + $env:PATH
Push-Location -LiteralPath $frontendRoot
try {
    if ($Action -eq 'install') {
        $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
        $pnpmExecutable = if ($pnpmCommand) { $pnpmCommand.Source } else { Join-Path $runtimeRoot 'bin/fallback/pnpm.cmd' }
        if (-not (Test-Path -LiteralPath $pnpmExecutable)) { throw 'Install pnpm 11 or newer, then run this script again.' }
        & $pnpmExecutable install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    } elseif ($Action -eq 'build') {
        & $nodeExecutable node_modules/typescript/bin/tsc -b
        if ($LASTEXITCODE -ne 0) { throw 'TypeScript validation failed.' }
        & $nodeExecutable node_modules/vite/bin/vite.js build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } else {
        & $nodeExecutable node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
    }
} finally { Pop-Location }
