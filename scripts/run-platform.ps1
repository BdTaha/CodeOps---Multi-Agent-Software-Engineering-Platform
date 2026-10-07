param([ValidateSet('api','worker')][string]$Service = 'api')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    $env:PATH = 'C:\Program Files\Docker\Docker\resources\bin;C:\Program Files\Git\cmd;' + $env:PATH
    $python = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if ($Service -eq 'api') {
        & $python -m uvicorn autonomous_engineering.platform:create_platform_app --factory --host 127.0.0.1 --port 8765
    } else {
        & $python -m autonomous_engineering.application.worker
    }
    if ($LASTEXITCODE -ne 0) { throw "$Service exited with an error." }
} finally { Pop-Location }
