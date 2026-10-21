# Starts Regista on this PC, at http://127.0.0.1:8090/ (or the port given). Needs Docker Desktop and Ollama, costs nothing.
# Usage: .\run.ps1                      works on the pictures in .\foto
#        .\run.ps1 -Photos D:\Immagini  works on another folder
#        .\run.ps1 -ReadOnly            can only look at the pictures: no trash, no copies
#        .\run.ps1 -Phone               also opens the door of the phones to the home network
#        .\run.ps1 -Phone -Address 100.64.0.7   adds another address where a phone can find this PC
#        .\run.ps1 -Open                opens the page in the browser once the app answers
#        .\run.ps1 -Port 8091 -PhonePort 8444   other doors, for a second Regista on the same PC
# The app never deletes a picture. What it throws away goes to .regista\cestino inside the
# picture folder, copies go to Raccolte, and both happen only after a yes in the page.
# The door of the phones is encrypted and lets in only a phone paired from this PC's page.
param(
    [string]$Photos = (Join-Path $PSScriptRoot 'foto'),
    [switch]$ReadOnly,
    [switch]$Phone,
    [string[]]$Address = @(),
    [switch]$Open,
    [int]$Port = 8090,
    [int]$PhonePort = 8443
)

function Stop-Run($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Photos -PathType Container)) { Stop-Run "the folder $Photos does not exist" }
try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 5 | Out-Null }
catch { Stop-Run 'Ollama is not running on this PC: start it and retry' }

# The app runs in a container and cannot see the computer the models run on.
# So the computer is measured here and passed in: the app uses it to choose a model that fits.
. (Join-Path $PSScriptRoot 'tools\computer.ps1')
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
# The door of the phones opens on this PC's address on the home network, and on no other: on another
# network, a cafe's Wi-Fi, that address is not there, and the door stays shut by itself.
$env:PHONE_BIND = if ($Phone) { $addresses[0] } else { '127.0.0.1' }
$env:HOST_ADDRESSES = $addresses -join ','
$env:HOST_NAME = $env:COMPUTERNAME
$env:PAGE_PORT = $Port
$env:PHONE_HOST_PORT = $PhonePort

# The page is built outside the image, where the sources are: the folder another PC installs from
# has it built already, and no tools to build it (tools\package.ps1).
$sources = Join-Path $PSScriptRoot 'web\src'
if (Test-Path $sources) {
    $built = Get-Item (Join-Path $PSScriptRoot 'web\dist\index.html') -ErrorAction SilentlyContinue
    $newest = Get-ChildItem $sources, (Join-Path $PSScriptRoot 'web\index.html'), (Join-Path $PSScriptRoot 'web\package.json') -Recurse -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $built -or $newest.LastWriteTime -gt $built.LastWriteTime) {
        & (Join-Path $PSScriptRoot 'npm.ps1') run build
        if ($LASTEXITCODE -ne 0) { Stop-Run 'building the page' }
    }
}

$files = @('-f', (Join-Path $PSScriptRoot 'compose.yaml'))
if ($Phone -and $addresses.Count -gt 1) {
    # the other addresses (a second network card, a private network such as Tailscale) open the door there too
    $more = Join-Path $env:TEMP 'regista-door.yaml'
    $lines = @('services:', '  regista:', '    ports:') + @($addresses | Select-Object -Skip 1 | ForEach-Object { "      - `"$($_):$($PhonePort):8443`"" })
    Set-Content -Path $more -Value $lines -Encoding ascii
    $files += @('-f', $more)
}
docker compose @files up -d --build
if ($LASTEXITCODE -ne 0) {
    # When the door of the phones goes from open to closed, or back, Docker may still be holding its
    # port for the app that was running: a moment later it is free.
    Start-Sleep -Seconds 3
    docker compose @files up -d
    if ($LASTEXITCODE -ne 0) { Stop-Run 'docker compose up' }
}

Write-Host "`nRegista: http://127.0.0.1:$Port/" -ForegroundColor Green
$access = if ($ReadOnly) { 'read only' } else { 'trash and copies allowed, after a yes in the page' }
Write-Host "Pictures: $($env:PHOTOS_DIR) ($access)" -ForegroundColor Green
if ($Phone) {
    Write-Host "Phones: can connect at $($addresses -join ', '), port $PhonePort, and only there, after pairing from the page" -ForegroundColor Green
    Write-Host "        If the phone does not find the PC, Windows Firewall may be blocking port $PhonePort on this network." -ForegroundColor DarkGray
} else {
    Write-Host "Phones: the door is closed to the network (start with -Phone to open it)" -ForegroundColor DarkGray
}
Write-Host "Stop it with: docker compose -f `"$(Join-Path $PSScriptRoot 'compose.yaml')`" down" -ForegroundColor DarkGray

if ($Open) {
    # the page, as soon as the app answers: after the first start that can take a little
    foreach ($attempt in 1..90) {
        try { Invoke-RestMethod http://127.0.0.1:$Port/healthz -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
    }
    Start-Process "http://127.0.0.1:$Port/"
}
