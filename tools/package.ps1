# Makes the folder another PC installs Regista from: the app, its page already built, the phone app
# already built, and the installer. Nothing of how they are made: no sources of the page or of the
# phone app, no tests, no pictures. Whoever gets it double-clicks install.cmd.
# Usage: tools\package.ps1 <folder>      the folder is made, or emptied first if it is one made by this
param([Parameter(Mandatory, Position = 0)][string]$Out)

$root = Split-Path $PSScriptRoot -Parent
function Stop-Run($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }

# a folder made by this script before is made again; any other folder that is not empty is left alone
if (Test-Path $Out) {
    if (-not (Test-Path (Join-Path $Out 'install.cmd')) -and (Get-ChildItem $Out -Force | Select-Object -First 1)) { Stop-Run "$Out is not empty, and is not a folder made by this script" }
    Get-ChildItem $Out -Force | Where-Object { $_.Name -notin @('models', 'Regista.cmd') } | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force $Out | Out-Null

# the page and the phone app, built now from the sources as they are
& (Join-Path $root 'npm.ps1') run build
if ($LASTEXITCODE -ne 0) { Stop-Run 'building the page' }
& (Join-Path $root 'android.ps1') build
if ($LASTEXITCODE -ne 0) { Stop-Run 'building the phone app' }

$take = @('app', 'data\geonames', 'web\dist', 'Dockerfile', '.dockerignore', 'compose.yaml', 'requirements.txt', 'run.ps1',
          'install.ps1', 'install.cmd', 'tools\computer.ps1', 'tools\phone-models.ps1', 'README.md')
foreach ($part in $take) {
    $from = Join-Path $root $part
    $to = Join-Path $Out $part
    New-Item -ItemType Directory -Force (Split-Path $to -Parent) | Out-Null
    Copy-Item -Recurse -Force $from $to
}
# nothing the Python of this PC left behind
Get-ChildItem $Out -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

# the phone app: the file for almost every phone, and the one for old phones with a 32-bit processor
$apps = Join-Path $root 'android\app\build\outputs\apk\release'
$phone = Join-Path $Out 'Per il telefono'
New-Item -ItemType Directory -Force $phone | Out-Null
Copy-Item (Join-Path $apps 'app-arm64-v8a-release.apk') (Join-Path $phone 'Regista.apk')
Copy-Item (Join-Path $apps 'app-armeabi-v7a-release.apk') (Join-Path $phone 'Regista per telefoni vecchi (32 bit).apk')

$size = (Get-ChildItem $Out -Recurse -File | Where-Object { $_.FullName -notlike '*\models\*' } | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("Ready: {0} ({1:0} MB). There, install.cmd sets Regista up." -f $Out, $size) -ForegroundColor Green
