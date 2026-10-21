# Measures this PC: the processor, the memory, the graphics card and its memory, the free disk.
# Dot-sourced by run.ps1, which passes the numbers to the app (it runs in a container and cannot see
# the computer), and by install.ps1, which uses them to choose the model that fits.
# Gives $computer, and sets HOST_GPU_NAME, HOST_GPU_MB, HOST_GPU_KIND, HOST_RAM_MB and HOST_CORES.

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
$processor = Get-CimInstance Win32_Processor
$env:HOST_CORES = ($processor | Measure-Object -Property NumberOfCores -Sum).Sum

$computer = [pscustomobject]@{
    Processor = ($processor | Select-Object -First 1).Name.Trim()
    Cores     = [int]$env:HOST_CORES
    RamGB     = [math]::Round([double]$env:HOST_RAM_MB / 1024)
    Gpu       = $env:HOST_GPU_NAME
    GpuGB     = [math]::Round([double]$env:HOST_GPU_MB / 1024, 1)
    GpuKind   = $env:HOST_GPU_KIND
    # the free space on the disk this folder is on, where Docker and Ollama usually keep their files too
    FreeGB    = [math]::Floor((Get-PSDrive -Name (Split-Path $PSScriptRoot -Qualifier).TrimEnd(':')).Free / 1GB)
    Bits64    = [Environment]::Is64BitOperatingSystem
}
