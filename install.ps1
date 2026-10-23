# Sets Regista up on a Windows PC, step by step: measures the computer, chooses the model that fits
# it, says what it will download and asks once, installs what is missing, starts the app and leaves
# an icon on the desktop. Run it by double-clicking install.cmd.
#
# What Regista needs, and what this does about each:
#   Docker Desktop     runs the app. If missing, installs it with winget (Windows' own installer).
#   Ollama             runs the model that directs. The same.
#   the director       the lightest model that does the job well on this computer: qwen3.5:4b with an
#                      NVIDIA card of 4 GB or more, or 16 GB of memory; granite4.1:3b otherwise. Qwen also
#                      sees: it looks at the pictures a search finds, one by one, and keeps the right ones.
#   the picture models two small models that read pictures and sentences, here and on the phone (220 MB).
# Nothing is downloaded or installed without a yes typed here: one yes, for the list it shows.
# At the least: Windows 10 or 11 at 64 bits, 8 GB of memory, 10 GB free on the disk.
#
# Usage: .\install.ps1                       asks what it needs to know
#        .\install.ps1 -Check                only measures, and says what is there and what is missing
#        .\install.ps1 -Photos D:\Immagini   the picture folder, without asking
#        .\install.ps1 -Yes                  yes to the downloads, without asking
#        .\install.ps1 -Icon D:\Avvio        puts the icon in that folder instead of on the desktop
#        .\install.ps1 -Phone yes            the app will be used from a phone too, without asking
#        .\install.ps1 -Port 8091 -PhonePort 8444   other doors: a second Regista on the same PC
#        .\install.ps1 -NoOpen               does not open the page in the browser at the end
# Windows lets a .ps1 file run only when asked for that one time: install.cmd and the icon do it,
# so nothing in the settings of Windows has to change.
param(
    [string]$Photos = '',
    [switch]$Check,
    [switch]$Yes,
    [string]$Icon = [Environment]::GetFolderPath('Desktop'),
    [ValidateSet('', 'yes', 'no')][string]$Phone = '',
    [int]$Port = 8090,
    [int]$PhonePort = 8443,
    [switch]$NoOpen
)

$here = $PSScriptRoot
. (Join-Path $here 'tools\computer.ps1')

function Say($text, $colour = 'Gray') { Write-Host $text -ForegroundColor $colour }
function Stop-Here($text) { Say "`n$text" 'Yellow'; exit 1 }
function Confirm-Step($question) {
    if ($Yes) { return $true }
    return (Read-Host "$question [s/N]") -match '^(s|si|sì|y|yes)$'
}
function Test-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Size($gb) { return ('{0:0.#} GB' -f $gb).Replace('.', ',') }

# Installs a program with winget, Windows' own installer, which shows where it comes from and its licence.
function Install-With-Winget($name, $id) {
    if (-not (Test-Command 'winget')) {
        Stop-Here "$name non c'è, e su questo PC manca winget per installarlo da qui. Installalo dal suo sito e rilancia questo file."
    }
    winget install --exact --id $id --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-Here "L'installazione di $name non è andata a buon fine. Installalo dal suo sito e rilancia questo file." }
}

Say "`nRegista: preparo questo computer.`n" 'Cyan'

# ---- 1. the computer, and the model that fits it

Say '1. Il computer' 'Cyan'
Say "   Processore:     $($computer.Processor) ($($computer.Cores) core)"
Say "   Memoria:        $($computer.RamGB) GB"
Say ("   Scheda video:   " + $(if ($computer.Gpu) { "$($computer.Gpu), $(Size $computer.GpuGB)" } else { 'nessuna che serva: il modello userà il processore' }))
Say "   Disco libero:   $($computer.FreeGB) GB"
$short = @()
if (-not $computer.Bits64) { $short += 'Windows a 64 bit' }
if ($computer.RamGB -lt 8) { $short += "almeno 8 GB di memoria (ne ha $($computer.RamGB))" }
if ($computer.FreeGB -lt 10) { $short += "almeno 10 GB liberi sul disco (ce ne sono $($computer.FreeGB))" }
if ($short) { Stop-Here "Questo computer non basta per Regista: servono $($short -join ', ')." }

# The model that directs: the lightest that does the job well here. Measured on this project's own test
# (selftest.py): qwen3.5:4b right in 17 cases of 17 and 98 decisions of 99, granite4.1:3b in 13 of 17.
# Qwen wants a graphics card of 4 GB, or the memory to run on the processor at a bearable speed.
if (($computer.GpuKind -eq 'nvidia' -and $computer.GpuGB -ge 4) -or $computer.RamGB -ge 16) {
    $model = [pscustomobject]@{ Name = 'qwen3.5:4b'; GB = 3.3; Why = 'il migliore che ci sta: alle prove ha capito 98 richieste su 99, e guarda le foto trovate una per una' }
} else {
    $model = [pscustomobject]@{ Name = 'granite4.1:3b'; GB = 2.1; Why = 'il più leggero che fa bene il lavoro con questa memoria' }
}
Say "   Modello regista: $($model.Name), $($model.Why)." 'Green'

# ---- 2. what is there, and what is missing

$docker = Test-Command 'docker'
$dockerOn = $false
if ($docker) { docker info 2>$null | Out-Null; $dockerOn = $LASTEXITCODE -eq 0 }
$ollamaOn = $false
$models = @()
try {
    $models = @((Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5).models | ForEach-Object { $_.name })
    $ollamaOn = $true
} catch {}
$ollama = $ollamaOn -or (Test-Command 'ollama')
# a model that directs well already there is enough: nothing is downloaded twice. A copy of Qwen made
# without its eyes, by an earlier version of this file, is not: Qwen whole shares its files, and adds the eyes.
$present = $models | Where-Object { $_ -in @('qwen3.5:4b', 'granite4.1:3b') } | Select-Object -First 1
$sees = @('vision.onnx', 'text.onnx', 'vocab.txt', 'dense.safetensors') | Where-Object { -not (Test-Path (Join-Path $here "models\phone\$_")) }

Say "`n2. Cosa serve" 'Cyan'
$downloads = @()
Say ("   Docker Desktop:  " + $(if ($dockerOn) { 'c''è ed è acceso' } elseif ($docker) { 'c''è, ma è spento' } else { 'manca' }))
if (-not $docker) { $downloads += [pscustomobject]@{ What = 'Docker Desktop'; GB = 0.6 } }
Say ("   Ollama:          " + $(if ($ollamaOn) { 'c''è ed è acceso' } elseif ($ollama) { 'c''è, ma è spento' } else { 'manca' }))
if (-not $ollama) { $downloads += [pscustomobject]@{ What = 'Ollama'; GB = 1.0 } }
Say ("   Modello regista: " + $(if ($present) { "c'è ($present)" } else { "da scaricare ($($model.Name), $(Size $model.GB))" }))
if (-not $present) { $downloads += [pscustomobject]@{ What = $model.Name; GB = $model.GB } }
Say ("   Modelli che leggono le foto: " + $(if ($sees) { 'da scaricare (0,2 GB)' } else { 'ci sono' }))
if ($sees) { $downloads += [pscustomobject]@{ What = 'i modelli che leggono le foto'; GB = 0.2 } }
Say '   Il programma:    lo costruisce Docker la prima volta (0,4 GB)'
$downloads += [pscustomobject]@{ What = 'il programma'; GB = 0.4 }
if ($Check) { exit 0 }

$total = ($downloads | Measure-Object -Property GB -Sum).Sum
Say "`n   In tutto scarico circa $(Size $total): $(($downloads | ForEach-Object { $_.What }) -join ', ')."
if (-not (Confirm-Step '   Procedo?')) { Stop-Here 'Non ho scaricato né installato niente. Rilancia questo file quando vuoi.' }

if (-not $docker) {
    Install-With-Winget 'Docker Desktop' 'Docker.DockerDesktop'
    Stop-Here "Docker Desktop è installato. Aprilo una volta dal menu Start, accetta le sue condizioni e aspetta che dica di essere acceso (può chiedere di riavviare il PC). Poi rilancia questo file: il resto lo fa da solo."
}
if (-not $dockerOn) { Stop-Here "Docker Desktop è spento: aprilo dal menu Start, aspetta che dica di essere acceso e rilancia questo file." }

if (-not $ollama) {
    Install-With-Winget 'Ollama' 'Ollama.Ollama'
    # it starts by itself once installed: a minute to answer
    foreach ($second in 1..60) {
        try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null; $ollamaOn = $true; break } catch { Start-Sleep -Seconds 1 }
    }
}
if (-not $ollamaOn) { Stop-Here "Ollama è spento: aprilo dal menu Start e rilancia questo file." }
if (-not (Test-Command 'ollama')) { $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama" }

if (-not $present) {
    ollama pull $model.Name
    if ($LASTEXITCODE -ne 0) { Stop-Here "Non sono riuscito a scaricare il modello. Riprova più tardi rilanciando questo file." }
}

if ($sees) {
    & (Join-Path $here 'tools\phone-models.ps1')
    if ($LASTEXITCODE -ne 0) { Stop-Here 'I modelli che leggono le foto non sono arrivati interi. Rilancia questo file.' }
}

# ---- 3. which pictures

if (-not $Photos) {
    $usual = [Environment]::GetFolderPath('MyPictures')
    Say "`n3. Le foto" 'Cyan'
    Say "   Su quale cartella lavoro? Regista non cancella mai niente: quello che butta va in un suo cestino dentro la cartella, e solo dopo un tuo sì."
    $typed = Read-Host "   Cartella delle foto (Invio per $usual)"
    $Photos = if ($typed) { $typed.Trim('"') } else { $usual }
}
if (-not (Test-Path $Photos -PathType Container)) { Stop-Here "La cartella $Photos non esiste." }
$Photos = (Resolve-Path $Photos).Path

# ---- 4. from a phone too?

if (-not $Phone) {
    Say "`n4. Il telefono" 'Cyan'
    Say "   Userai Regista anche dal telefono? Allora il computer apre, solo sulla rete di casa, una porta cifrata che fa entrare solo un telefono che colleghi tu."
    $Phone = if ((Read-Host '   Anche dal telefono? [s/N]') -match '^(s|si|sì|y|yes)$') { 'yes' } else { 'no' }
}

# ---- 5. an icon to start it again, and the first start

$more = @()
if ($Phone -eq 'yes') { $more += '-Phone' }
if ($Port -ne 8090) { $more += "-Port $Port" }
if ($PhonePort -ne 8443) { $more += "-PhonePort $PhonePort" }
# A file that starts Regista on that folder and opens its page: the icon on the desktop points to it.
$starter = Join-Path $here 'Regista.cmd'
# in the alphabet cmd reads its files in, so that a folder with an accent in its name still works
Set-Content -Path $starter -Encoding Oem -Value @(
    '@echo off',
    "powershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0run.ps1`" -Photos `"$Photos`" $($more -join ' ') -Open",
    'if errorlevel 1 pause'
)
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $Icon 'Regista.lnk'))
$shortcut.TargetPath = $starter
$shortcut.WorkingDirectory = $here
$shortcut.Description = 'Regista: il tuo assistente, in locale'
$shortcut.Save()
Say "`n5. Fatto: l'icona «Regista» è in $Icon, da lì si avvia." 'Green'
$app = Join-Path $here 'Per il telefono'
if ($Phone -eq 'yes' -and (Test-Path $app)) {
    Say "   L'app per il telefono è nella cartella «$app»: copiala sul telefono e aprila (Android chiede di permettere l'installazione). Poi collegalo dalla pagina di Regista, alla voce «Telefono»."
}
Say "`nAvvio Regista. La prima volta costruisce il programma e ci mette qualche minuto.`n" 'Cyan'
$start = @{ Photos = $Photos; Port = $Port; PhonePort = $PhonePort; Open = -not $NoOpen }
if ($Phone -eq 'yes') { $start.Phone = $true }
& (Join-Path $here 'run.ps1') @start
exit $LASTEXITCODE
