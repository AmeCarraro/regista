# Starts Regista on this PC, at http://127.0.0.1:8090/. Needs Docker Desktop and Ollama, costs nothing.
# Usage: .\run.ps1                      works on the pictures in .\foto
#        .\run.ps1 -Photos D:\Immagini  works on another folder
#        .\run.ps1 -ReadOnly            can only look at the pictures: no trash, no copies
# The app never deletes a picture. What it throws away goes to .regista\cestino inside the
# picture folder, copies go to Raccolte, and both happen only after a yes in the page.
param(
    [string]$Photos = (Join-Path $PSScriptRoot 'foto'),
    [switch]$ReadOnly
)

function Stop-Run($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Photos -PathType Container)) { Stop-Run "the folder $Photos does not exist" }
try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 5 | Out-Null }
catch { Stop-Run 'Ollama is not running on this PC: start it and retry' }

# The app runs in a container and cannot see the computer the models run on.
# So the computer is measured here and passed in: the app uses it to choose a model that fits.
$gpu = $null
try { $gpu = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1 } catch {}
if ($gpu) {
    $parts = $gpu -split ',\s*'
    $env:HOST_GPU_NAME = $parts[0]
    $env:HOST_GPU_MB = $parts[1]
} else {
    # no NVIDIA card: the models will run on the processor
    $env:HOST_GPU_NAME = ''
    $env:HOST_GPU_MB = '0'
}
$env:HOST_RAM_MB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
$env:HOST_CORES = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum
$env:PHOTOS_DIR = (Resolve-Path $Photos).Path
$env:PHOTOS_READ_ONLY = if ($ReadOnly) { 'true' } else { 'false' }

docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d --build
if ($LASTEXITCODE -ne 0) { Stop-Run 'docker compose up' }

Write-Host "`nRegista: http://127.0.0.1:8090/" -ForegroundColor Green
$access = if ($ReadOnly) { 'read only' } else { 'trash and copies allowed, after a yes in the page' }
Write-Host "Pictures: $($env:PHOTOS_DIR) ($access)" -ForegroundColor Green
Write-Host "Stop it with: docker compose -f `"$(Join-Path $PSScriptRoot 'compose.yaml')`" down" -ForegroundColor DarkGray
