#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
# Repair the missing MSI installation without unregistering any distributions.
$release = Invoke-RestMethod 'https://api.github.com/repos/microsoft/WSL/releases/latest'
$architecture = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
$asset = $release.assets | Where-Object { $_.name -like "*.$architecture.msi" } | Select-Object -First 1
if (-not $asset -or $asset.browser_download_url -notlike 'https://github.com/microsoft/WSL/releases/download/*') {
    throw 'The official Microsoft WSL release did not contain the expected MSI.'
}
$installer = Join-Path $env:TEMP $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installer
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'The installer did not pass Microsoft signature validation. Installation was not started.'
}
Write-Host "Verified Microsoft installer: $installer"
Write-Host 'Complete the installer. Do not unregister or reset any existing WSL distributions.'
Start-Process -FilePath 'msiexec.exe' -ArgumentList @('/i', ('"' + $installer + '"'), '/norestart') -Wait
& "$env:SystemRoot\System32\wsl.exe" --version
Write-Host 'If Windows requests a restart, save your work and restart manually, then open Docker Desktop.'
