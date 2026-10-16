# Sets Regista up on a Windows PC: checks what it needs, asks before downloading anything,
# starts it and leaves an icon on the desktop. Run it by double-clicking install.cmd.
#
# What Regista needs, and what this does about each:
#   Docker Desktop   runs the app. If missing, offers to install it with winget (Windows' own installer).
#   Ollama           runs the models. The same.
#   a model          the director. If none is there, offers to download granite4.1:3b (2.1 GB).
# Nothing is downloaded or installed without a yes typed here. The first start then builds the
# app, which downloads about 3 GB more (PyTorch and the model that reads pictures) and takes
# some minutes; the starts after that take seconds.
#
# Usage: .\install.ps1                       asks what it needs to know
#        .\install.ps1 -Check                only says what is there and what is missing
#        .\install.ps1 -Photos D:\Immagini   the picture folder, without asking
#        .\install.ps1 -Yes                  yes to every download, without asking
#        .\install.ps1 -Icon D:\Avvio        puts the icon in that folder instead of on the desktop
#        .\install.ps1 -Phone yes            the app will be used from a phone too, without asking
# Windows lets a .ps1 file run only when asked for that one time: install.cmd and the icon do it,
# so nothing in the settings of Windows has to change.
param(
    [string]$Photos = '',
    [switch]$Check,
    [switch]$Yes,
    [string]$Icon = [Environment]::GetFolderPath('Desktop'),
    [ValidateSet('', 'yes', 'no')][string]$Phone = ''
)

$here = $PSScriptRoot
$model = 'granite4.1:3b'

function Say($text, $colour = 'Gray') { Write-Host $text -ForegroundColor $colour }
function Stop-Here($text) { Say "`n$text" 'Yellow'; exit 1 }
function Confirm-Step($question) {
    if ($Yes) { return $true }
    return (Read-Host "$question [s/N]") -match '^(s|si|sì|y|yes)$'
}
function Test-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Installs a program with winget, after a yes. winget shows where the program comes from and its licence.
function Install-With-Winget($name, $id, $size) {
    if (-not (Test-Command 'winget')) {
        Stop-Here "$name non c'è, e su questo PC manca winget per installarlo da qui. Installalo dal suo sito e rilancia questo file."
    }
    if (-not (Confirm-Step "$name non c'è. Lo installo ora con winget? Scarica circa $size.")) {
        Stop-Here "Senza $name Regista non parte. Installalo quando vuoi e rilancia questo file."
    }
    winget install --exact --id $id
    if ($LASTEXITCODE -ne 0) { Stop-Here "L'installazione di $name non è andata a buon fine. Installalo dal suo sito e rilancia questo file." }
}

Say "`nRegista: preparo questo computer.`n" 'Cyan'

# ---- what is there

$docker = Test-Command 'docker'
$dockerOn = $false
if ($docker) { docker info 2>$null | Out-Null; $dockerOn = $LASTEXITCODE -eq 0 }
$ollamaOn = $false
$models = @()
try {
    $models = @((Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5).models | ForEach-Object { $_.name })
    $ollamaOn = $true
} catch {}
# one that answers is there, wherever it was installed
$ollama = $ollamaOn -or (Test-Command 'ollama')
# any model that can direct will do; the page then says which one is best for this computer
$hasModel = [bool]($models | Where-Object { $_ -like 'granite4.1:*' })

Say ("Docker Desktop: " + $(if ($dockerOn) { 'c''è ed è acceso' } elseif ($docker) { 'c''è, ma è spento' } else { 'manca' }))
Say ("Ollama:         " + $(if ($ollamaOn) { 'c''è ed è acceso' } elseif ($ollama) { 'c''è, ma è spento' } else { 'manca' }))
Say ("Modello:        " + $(if ($hasModel) { 'c''è' } elseif ($ollamaOn) { "manca ($model, 2,1 GB)" } else { 'lo controllo quando Ollama è acceso' }))
if ($Check) { exit 0 }

# ---- what is missing

if (-not $docker) {
    Install-With-Winget 'Docker Desktop' 'Docker.DockerDesktop' '600 MB'
    Stop-Here "Docker Desktop è installato. Aprilo una volta dal menu Start, accetta le sue condizioni e aspetta che dica di essere acceso (può chiedere di riavviare il PC). Poi rilancia questo file."
}
if (-not $dockerOn) { Stop-Here "Docker Desktop è spento: aprilo dal menu Start, aspetta che dica di essere acceso e rilancia questo file." }

if (-not $ollama) {
    Install-With-Winget 'Ollama' 'Ollama.Ollama' '1 GB'
    Stop-Here "Ollama è installato. Aprilo una volta dal menu Start e rilancia questo file."
}
if (-not $ollamaOn) { Stop-Here "Ollama è spento: aprilo dal menu Start e rilancia questo file." }

if (-not $hasModel) {
    if (-not (Confirm-Step "Manca il modello che fa da regista. Scarico $model (2,1 GB)?")) {
        Stop-Here "Senza un modello Regista non può decidere cosa fare. Per scaricarlo più tardi: ollama pull $model"
    }
    if (-not (Test-Command 'ollama')) { Stop-Here "Ollama risponde, ma da qui non trovo il suo comando. Apri un terminale nuovo, scrivi: ollama pull $model  e poi rilancia questo file." }
    ollama pull $model
    if ($LASTEXITCODE -ne 0) { Stop-Here "Non sono riuscito a scaricare il modello. Riprova più tardi con: ollama pull $model" }
}

# ---- which pictures

if (-not $Photos) {
    $usual = [Environment]::GetFolderPath('MyPictures')
    Say "`nSu quale cartella di foto lavoro? Regista non cancella mai niente: quello che butta va in un suo cestino dentro la cartella, e solo dopo un tuo sì."
    $typed = Read-Host "Cartella delle foto (Invio per $usual)"
    $Photos = if ($typed) { $typed.Trim('"') } else { $usual }
}
if (-not (Test-Path $Photos -PathType Container)) { Stop-Here "La cartella $Photos non esiste." }
$Photos = (Resolve-Path $Photos).Path

# ---- from a phone too?

if (-not $Phone) {
    Say "`nUserai Regista anche dal telefono, con la sua app? Allora il computer apre una porta per i telefoni, cifrata, che fa entrare solo un telefono collegato da qui."
    $Phone = if ((Read-Host 'Anche dal telefono? [s/N]') -match '^(s|si|sì|y|yes)$') { 'yes' } else { 'no' }
}
$door = if ($Phone -eq 'yes') { ' -Phone' } else { '' }

# ---- an icon to start it again, and the first start

# A file that starts Regista on that folder and opens its page: the icon on the desktop points to it.
$starter = Join-Path $here 'Regista.cmd'
# in the alphabet cmd reads its files in, so that a folder with an accent in its name still works
Set-Content -Path $starter -Encoding Oem -Value @(
    '@echo off',
    "powershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0run.ps1`" -Photos `"$Photos`"$door -Open",
    'if errorlevel 1 pause'
)
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $Icon 'Regista.lnk'))
$shortcut.TargetPath = $starter
$shortcut.WorkingDirectory = $here
$shortcut.Description = 'Regista: il tuo assistente, in locale'
$shortcut.Save()
Say "`nHo messo l'icona «Regista» in $Icon`: da ora si avvia da lì." 'Green'

Say "Avvio Regista. La prima volta costruisce l'app: scarica circa 3 GB e ci mette qualche minuto.`n" 'Cyan'
if ($Phone -eq 'yes') { & (Join-Path $here 'run.ps1') -Photos $Photos -Phone -Open } else { & (Join-Path $here 'run.ps1') -Photos $Photos -Open }
exit $LASTEXITCODE
