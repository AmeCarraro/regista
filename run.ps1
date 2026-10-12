# Starts Regista on this PC, at http://127.0.0.1:8090/. Needs Docker Desktop and Ollama, costs nothing.
# Usage: .\run.ps1                      works on the pictures in .\foto
#        .\run.ps1 -Photos D:\Immagini  works on another folder
#        .\run.ps1 -ReadOnly            can only look at the pictures: no trash, no copies
#        .\run.ps1 -Phone               also opens the door of the phones to the home network
#        .\run.ps1 -Phone -Address 100.64.0.7   adds another address where a phone can find this PC
#        .\run.ps1 -Open                opens the page in the browser once the app answers
# The app never deletes a picture. What it throws away goes to .regista\cestino inside the
# picture folder, copies go to Raccolte, and both happen only after a yes in the page.
# The door of the phones is encrypted and lets in only a phone paired from this PC's page.
param(
    [string]$Photos = (Join-Path $PSScriptRoot 'foto'),
    [switch]$ReadOnly,
    [switch]$Phone,
    [string[]]$Address = @(),
    [switch]$Open
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
    $env:HOST_GPU_KIND = 'nvidia'
} else {
    # No NVIDIA card. Windows knows the other cards, and the video memory each has for itself: the
    # registry says it in full, while Win32_VideoController stops at 4 GB. A card built into the
    # processor has next to none, and is not counted. Whether Ollama uses the card found cannot be
    # known from here: the app counts on it only after seeing a model run on it.
    $class = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    $card = Get-ChildItem $class -ErrorAction SilentlyContinue | ForEach-Object {
        $known = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        if ($known.DriverDesc) { [pscustomobject]@{ Name = $known.DriverDesc; MB = [math]::Round([double]$known.'HardwareInformation.qwMemorySize' / 1MB) } }
    } | Sort-Object MB -Descending | Select-Object -First 1
    if ($card -and $card.MB -ge 2048) {
        $env:HOST_GPU_NAME = $card.Name
        $env:HOST_GPU_MB = $card.MB
        $env:HOST_GPU_KIND = 'other'
    } else {
        # the models will run on the processor
        $env:HOST_GPU_NAME = ''
        $env:HOST_GPU_MB = '0'
        $env:HOST_GPU_KIND = ''
    }
}
$env:HOST_RAM_MB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB)
$env:HOST_CORES = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum
$env:PHOTOS_DIR = (Resolve-Path $Photos).Path
$env:PHOTOS_READ_ONLY = if ($ReadOnly) { 'true' } else { 'false' }

# Nor can the app see where this PC is on the network. A phone needs to know: the addresses
# of the network cards that lead out (the ones with a gateway) go into the link that pairs it.
$addresses = @()
if ($Phone) {
    $addresses = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
        ForEach-Object { $_.IPv4Address.IPAddress }) + $Address
    if (-not $addresses) { Stop-Run 'this PC has no network address a phone could reach' }
}
$env:PHONE_OPEN = if ($Phone) { '1' } else { '0' }
$env:PHONE_BIND = if ($Phone) { '0.0.0.0' } else { '127.0.0.1' }
$env:HOST_ADDRESSES = $addresses -join ','
$env:HOST_NAME = $env:COMPUTERNAME

docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d --build
if ($LASTEXITCODE -ne 0) {
    # When the door of the phones goes from open to closed, or back, Docker may still be holding its
    # port for the app that was running: a moment later it is free.
    Start-Sleep -Seconds 3
    docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d
    if ($LASTEXITCODE -ne 0) { Stop-Run 'docker compose up' }
}

Write-Host "`nRegista: http://127.0.0.1:8090/" -ForegroundColor Green
$access = if ($ReadOnly) { 'read only' } else { 'trash and copies allowed, after a yes in the page' }
Write-Host "Pictures: $($env:PHOTOS_DIR) ($access)" -ForegroundColor Green
if ($Phone) {
    Write-Host "Phones: can connect at $($addresses -join ', '), port 8443, after pairing from the page" -ForegroundColor Green
    Write-Host "        If the phone does not find the PC, Windows Firewall may be blocking port 8443 on this network." -ForegroundColor DarkGray
} else {
    Write-Host "Phones: the door is closed to the network (start with -Phone to open it)" -ForegroundColor DarkGray
}
Write-Host "Stop it with: docker compose -f `"$(Join-Path $PSScriptRoot 'compose.yaml')`" down" -ForegroundColor DarkGray

if ($Open) {
    # the page, as soon as the app answers: after the first start that can take a little
    foreach ($attempt in 1..90) {
        try { Invoke-RestMethod http://127.0.0.1:8090/healthz -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
    }
    Start-Process 'http://127.0.0.1:8090/'
}
