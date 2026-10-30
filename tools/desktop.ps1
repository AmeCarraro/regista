# Makes the program of the PC, the one that needs no Docker, in build\Regista: the official Python 3.11 with the
# libraries of requirements-desktop.txt, the app, the page and the table of places, laid out as this repository.
# Its icon starts python\pythonw.exe app\desktop.py. No .exe is made here: Windows' Smart App Control, on in a new
# Windows 11, blocks a program nobody signed, and Python's own programs are signed by those who make it.
# The models are not in it: install.ps1 downloads them into its models\phone.
# Usage: .\tools\desktop.ps1           with the Python of .venv, made the first time from requirements-desktop.txt
#        .\tools\desktop.ps1 -Python C:\Python311\python.exe    makes .venv with that Python, if there is none yet
param([string]$Python = 'py')

function Stop-Build($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }

$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $root '.venv'
$inside = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $inside)) {
    if ($Python -eq 'py') { & py -3.11 -m venv $venv } else { & $Python -m venv $venv }
    if ($LASTEXITCODE -ne 0) { Stop-Build 'making .venv: Python 3.11 is needed (python.org)' }
}
& $inside -m pip install --disable-pip-version-check -q -r (Join-Path $root 'requirements-desktop.txt')
if ($LASTEXITCODE -ne 0) { Stop-Build 'installing the libraries' }

# the page, when its sources changed since it was last built
$sources = Join-Path $root 'web\src'
$built = Get-Item (Join-Path $root 'web\dist\index.html') -ErrorAction SilentlyContinue
$newest = Get-ChildItem $sources, (Join-Path $root 'web\index.html'), (Join-Path $root 'web\package.json') -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $built -or $newest.LastWriteTime -gt $built.LastWriteTime) {
    & (Join-Path $root 'npm.ps1') run build
    if ($LASTEXITCODE -ne 0) { Stop-Build 'building the page' }
}

# the Python .venv was made from: its own files, as python.org installed them
$base = (Get-Content (Join-Path $venv 'pyvenv.cfg') | Where-Object { $_ -match '^home\s*=' }) -replace '^home\s*=\s*', ''
if (-not (Test-Path (Join-Path $base 'pythonw.exe'))) { Stop-Build "no Python where .venv says it was made from: $base" }

$out = Join-Path $root 'build\Regista'
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
$runtime = Join-Path $out 'python'
New-Item -ItemType Directory -Force $runtime | Out-Null

function Copy-Tree($from, $to, [string[]]$leave) {
    # a folder and what is in it, but not the folders named in $leave, nor the compiled copies Python makes again by itself
    robocopy $from $to /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ @leave | Out-Null
    if ($LASTEXITCODE -ge 8) { Stop-Build "copying $from" }
}

foreach ($name in 'python.exe', 'pythonw.exe', 'python311.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt') {
    Copy-Item (Join-Path $base $name) $runtime
}
# the standard library, without its tests, its editor and the windows of Tk, which Regista does not use
Copy-Tree (Join-Path $base 'Lib') (Join-Path $runtime 'Lib') @('site-packages', 'test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3')
Copy-Tree (Join-Path $base 'DLLs') (Join-Path $runtime 'DLLs') @()
Remove-Item (Join-Path $runtime 'DLLs\_tkinter.pyd'), (Join-Path $runtime 'DLLs\tcl86t.dll'), (Join-Path $runtime 'DLLs\tk86t.dll') -ErrorAction SilentlyContinue
# the libraries, without the tools that only installed and built them, and without their tests
$packages = Join-Path $venv 'Lib\site-packages'
$tools = Get-ChildItem $packages -Directory | Where-Object { $_.Name -match '^(pip|setuptools|_distutils_hack|pkg_resources|pytest|_pytest|pluggy|iniconfig|pygments|PyInstaller|_pyinstaller_hooks_contrib|pyinstaller|altgraph|pefile|ordlookup|win32ctypes|pywin32_ctypes)([-_.].*)?$' } |
    ForEach-Object { $_.FullName }
Copy-Tree $packages (Join-Path $runtime 'Lib\site-packages') (@($tools) + @('tests', 'transformers', 'quantization'))
# and setuptools' note to Python, which would look for setuptools at every start
Remove-Item (Join-Path $runtime 'Lib\site-packages\distutils-precedence.pth') -ErrorAction SilentlyContinue
# what this Python looks at, and nothing else: no other Python of the PC, no settings of the user
Set-Content -Path (Join-Path $runtime 'python311._pth') -Encoding ascii -Value @('Lib', 'DLLs', 'Lib\site-packages', '..\app', 'import site')

# the app, laid out as here: what desktop.py expects next to it
Copy-Tree (Join-Path $root 'app') (Join-Path $out 'app') @()
Copy-Tree (Join-Path $root 'web\dist') (Join-Path $out 'web\dist') @()
Copy-Tree (Join-Path $root 'data\geonames') (Join-Path $out 'data\geonames') @()
New-Item -ItemType Directory -Force (Join-Path $out 'tools') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'regista.ico') (Join-Path $out 'tools')
# the phone app, when it was built (android.ps1 build): the phones take it from here, with no cable, when it is newer than theirs
$apps = Join-Path $root 'android\app\build\outputs\apk\release'
if (Test-Path (Join-Path $apps 'output-metadata.json')) {
    New-Item -ItemType Directory -Force (Join-Path $out 'phone-app') | Out-Null
    Copy-Item (Join-Path $apps '*.apk'), (Join-Path $apps 'output-metadata.json') (Join-Path $out 'phone-app')
} else {
    Write-Host 'The phone app is not built (android.ps1 build): the phones will not find a newer one here.' -ForegroundColor Yellow
}

# its Python finds the app and every library it needs, as it will when its icon starts it
& (Join-Path $runtime 'python.exe') -c "import importlib.util, desktop, uvicorn, fastapi, webview, onnxruntime, numpy, PIL, cryptography.x509, segno, httpx2; assert importlib.util.find_spec('main')"
if ($LASTEXITCODE -ne 0) { Stop-Build 'the program does not start' }
$size = (Get-ChildItem $out -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("`nRegista: {0} ({1:N0} MB). It starts with python\pythonw.exe app\desktop.py" -f $out, $size) -ForegroundColor Green
