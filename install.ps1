# Sets Regista up on a Windows PC, step by step: measures the computer, chooses the model that fits
# it, says what it will download and asks once, installs what is missing, puts the program in its
# folder, leaves an icon on the desktop and starts it. Run it by double-clicking install.cmd.
#
# What Regista needs, and what this does about each:
#   Ollama             runs the models. If missing, installs it with winget (Windows' own installer).
#   the director       the lightest model that does the job well on this computer: qwen3.5:4b with an
#                      NVIDIA card of 4 GB or more, or 16 GB of memory; granite4.1:3b otherwise. Qwen also
#                      sees: it looks at the pictures a search finds, one by one, and keeps the right ones.
#   the picture models two small models that read pictures and sentences, here and on the phone (220 MB).
#   the program        Regista itself, with the official Python inside it, signed by those who make it:
#                      copied from this folder, nothing to download, no Docker.
# Nothing is downloaded or installed without a yes typed here: one yes, for the list it shows.
# At the least: Windows 10 or 11 at 64 bits, 8 GB of memory, 10 GB free on the disk.
#
# Usage: .\install.ps1                       asks what it needs to know
#        .\install.ps1 -Check                only measures, and says what is there and what is missing
#        .\install.ps1 -Photos D:\Immagini   the picture folder, without asking
#        .\install.ps1 -Yes                  yes to the downloads, without asking
#        .\install.ps1 -Icon D:\Avvio        puts the icon in that folder instead of on the desktop
#        .\install.ps1 -Phone yes            the app will be used from a phone too, without asking
#        .\install.ps1 -Into D:\Regista      installs there, instead of in the user's own programs
#        .\install.ps1 -Port 8091 -PhonePort 8444   other doors: a second Regista on the same PC
#        .\install.ps1 -FromDocker regista-regista-1   takes along what the Docker version of Regista knew:
#                                            the pictures it read, the results of the model tests, the phones paired
#        .\install.ps1 -NoOpen               does not start it at the end
# Windows lets a .ps1 file run only when asked for that one time: install.cmd does it, so nothing in
# the settings of Windows has to change.
param(
    [string]$Photos = '',
    [switch]$Check,
    [switch]$Yes,
    [string]$Icon = [Environment]::GetFolderPath('Desktop'),
    [ValidateSet('', 'yes', 'no')][string]$Phone = '',
    [string]$Into = (Join-Path $env:LOCALAPPDATA 'Programs\Regista'),
    [int]$Port = 8090,
    [int]$PhonePort = 8443,
    [string]$FromDocker = '',
    [switch]$NoOpen
)

$here = $PSScriptRoot
. (Join-Path $here 'tools\computer.ps1')

function Say($text, $colour = 'Gray') { Write-Host $text -ForegroundColor $colour }
# a question; where nobody can answer it (a window that cannot ask), the answer is the one of Invio
function Ask($question) { try { Read-Host $question -ErrorAction Stop } catch { '' } }
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

# the program to install: next to this file in the folder made by tools\package.ps1, in build\ in the repository
$program = @((Join-Path $here 'Regista'), (Join-Path $here 'build\Regista')) | Where-Object { Test-Path (Join-Path $_ 'app\desktop.py') } | Select-Object -First 1
if (-not $program) { Stop-Here "Manca il programma da installare: qui accanto dovrebbe esserci la cartella «Regista» (nel repository la fa tools\desktop.ps1)." }
$Into = [IO.Path]::GetFullPath($Into)

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

$ollamaOn = $false
$models = @()
try {
    $models = @((Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5).models | ForEach-Object { $_.name })
    $ollamaOn = $true
} catch {}
$ollama = $ollamaOn -or (Test-Command 'ollama') -or (Test-Path (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'))
# a model that directs well already there is enough: nothing is downloaded twice. A copy of Qwen made
# without its eyes, by an earlier version of this file, is not: Qwen whole shares its files, and adds the eyes.
$present = $models | Where-Object { $_ -in @('qwen3.5:4b', 'granite4.1:3b') } | Select-Object -First 1
$sees = @('vision.onnx', 'text.onnx', 'vocab.txt', 'dense.safetensors') | Where-Object { -not (Test-Path (Join-Path $Into "models\phone\$_")) }
$size = (Get-ChildItem $program -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1GB

Say "`n2. Cosa serve" 'Cyan'
$downloads = @()
Say ("   Ollama:          " + $(if ($ollamaOn) { 'c''è ed è acceso' } elseif ($ollama) { 'c''è, ma è spento' } else { 'manca' }))
if (-not $ollama) { $downloads += [pscustomobject]@{ What = 'Ollama'; GB = 1.0 } }
Say ("   Modello regista: " + $(if ($present) { "c'è ($present)" } else { "da scaricare ($($model.Name), $(Size $model.GB))" }))
if (-not $present) { $downloads += [pscustomobject]@{ What = $model.Name; GB = $model.GB } }
Say ("   Modelli che leggono le foto: " + $(if ($sees) { 'da scaricare (0,2 GB)' } else { 'ci sono' }))
if ($sees) { $downloads += [pscustomobject]@{ What = 'i modelli che leggono le foto'; GB = 0.2 } }
Say "   Il programma:    è in questa cartella ($(Size $size)): lo copio in $Into"
if ($Check) { exit 0 }

if ($downloads) {
    $total = ($downloads | Measure-Object -Property GB -Sum).Sum
    Say "`n   In tutto scarico circa $(Size $total): $(($downloads | ForEach-Object { $_.What }) -join ', ')."
    if (-not (Confirm-Step '   Procedo?')) { Stop-Here 'Non ho scaricato né installato niente. Rilancia questo file quando vuoi.' }
}

if (-not $ollama) {
    Install-With-Winget 'Ollama' 'Ollama.Ollama'
}
if (-not $ollamaOn) {
    # Ollama starts by itself once installed, and at every start of Windows; after it was closed, from here
    $ollamaApp = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (Test-Path $ollamaApp) { Start-Process $ollamaApp }
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
    & (Join-Path $here 'tools\phone-models.ps1') -Into (Join-Path $Into 'models\phone')
    if ($LASTEXITCODE -ne 0) { Stop-Here 'I modelli che leggono le foto non sono arrivati interi. Rilancia questo file.' }
}

# what an earlier installation chose, offered again
$before = $null
$written = Join-Path $Into 'settings.json'
if (Test-Path $written) { try { $before = Get-Content $written -Raw -Encoding UTF8 | ConvertFrom-Json } catch {} }

# ---- 3. which pictures

if (-not $Photos) {
    $usual = if ($before -and $before.photos) { $before.photos } else { [Environment]::GetFolderPath('MyPictures') }
    Say "`n3. Le foto" 'Cyan'
    Say "   Su quale cartella lavoro? Regista non cancella mai niente: quello che butta va in un suo cestino dentro la cartella, e solo dopo un tuo sì."
    $typed = Ask "   Cartella delle foto (Invio per $usual)"
    $Photos = if ($typed) { $typed.Trim('"') } else { $usual }
}
if (-not (Test-Path $Photos -PathType Container)) { Stop-Here "La cartella $Photos non esiste." }
$Photos = (Resolve-Path $Photos).Path

# ---- 4. from a phone too?

if (-not $Phone) {
    # an update keeps what was chosen the time before, unless the user says otherwise
    $earlier = [bool]($before -and $before.phone)
    Say "`n4. Il telefono" 'Cyan'
    Say "   Userai Regista anche dal telefono? Allora il computer apre, solo sulla rete di casa, una porta cifrata che fa entrare solo un telefono che colleghi tu."
    $typed = Ask $(if ($earlier) { '   Anche dal telefono? [S/n]' } else { '   Anche dal telefono? [s/N]' })
    $Phone = if ($typed -match '^(s|si|sì|y|yes)$') { 'yes' } elseif ($typed -match '^(n|no)$') { 'no' } elseif ($earlier) { 'yes' } else { 'no' }
}

# ---- 5. the program in its folder, an icon to start it, and the first start

try { Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 2 | Out-Null; Stop-Here "Regista è aperto: chiudi la sua finestra e rilancia questo file." } catch {}
# a Regista closed a moment ago may still be ending, and hold its files: a few seconds for it
$python = Join-Path $Into 'python\pythonw.exe'
foreach ($second in 1..20) {
    if (-not (Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.ExecutablePath -eq $python })) { break }
    Start-Sleep -Seconds 1
}
New-Item -ItemType Directory -Force $Into | Out-Null
# its parts are put in again; what it knows stays: the index, settings.json, the models
foreach ($part in 'python', 'app', 'web', 'data', 'tools', 'phone-app') { Remove-Item -Recurse -Force (Join-Path $Into $part) -ErrorAction SilentlyContinue }
robocopy $program $Into /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Here "Non sono riuscito a copiare il programma in $Into." }

if ($FromDocker) {
    $index = Join-Path $Into 'index'
    if (Test-Path (Join-Path $index 'photos.json')) {
        Say "   Quello che sapeva la versione con Docker c'è già qui: non lo copio di nuovo."
    } else {
        New-Item -ItemType Directory -Force $index | Out-Null
        docker cp "$($FromDocker):/data/." $index
        if ($LASTEXITCODE -ne 0) { Stop-Here "Non sono riuscito a prendere i dati di ${FromDocker}: Docker Desktop è acceso?" }
        Say "   Ho preso dalla versione con Docker le foto già lette, le prove dei modelli e i telefoni collegati." 'Green'
    }
}

$settings = [ordered]@{ photos = $Photos; read_only = $false; phone = ($Phone -eq 'yes'); port = $Port; phone_port = $PhonePort; addresses = @() }
[IO.File]::WriteAllText((Join-Path $Into 'settings.json'), ($settings | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))

$python = Join-Path $Into 'python\pythonw.exe'
$start = "`"$(Join-Path $Into 'app\desktop.py')`""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $Icon 'Regista.lnk'))
$shortcut.TargetPath = $python
$shortcut.Arguments = $start
$shortcut.WorkingDirectory = $Into
$shortcut.IconLocation = Join-Path $Into 'tools\regista.ico'
$shortcut.Description = 'Regista: il tuo assistente, in locale'
$shortcut.Save()
Say "`n5. Fatto: Regista è in $Into, e l'icona «Regista» è in ${Icon}: da lì si avvia." 'Green'
if ($Phone -eq 'yes') {
    Say "   La prima volta Windows può chiederti se «Python» può usare la rete: è Regista, che apre la porta del telefono. Rispondi «Consenti»."
    $app = Join-Path $here 'Per il telefono'
    if (Test-Path $app) {
        Say "   L'app per il telefono è nella cartella «$app»: copiala sul telefono e aprila (Android chiede di permettere l'installazione). Poi collegalo dalla pagina di Regista, alla voce «Telefono»."
    }
}
if (-not $NoOpen) {
    Say "`nAvvio Regista: la sua finestra si apre tra qualche secondo.`n" 'Cyan'
    Start-Process $python -ArgumentList $start -WorkingDirectory $Into
}
exit 0
