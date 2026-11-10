# Builds the Android app and tries it on a pretend phone, all in containers: nothing Android is installed on the PC.
# Usage: .\android.ps1 build       makes the app, one file per kind of phone, in android\app\build\outputs\apk\release:
#                                  app-arm64-v8a-release.apk for almost every phone, app-armeabi-v7a-release.apk for old 32-bit ones
#        .\android.ps1 phone       starts a pretend phone (an Android 15 emulator, no window) and waits until it is on
#        .\android.ps1 phone 13    the same with Android 13, the Android of the phone the app is mostly used on
#        .\android.ps1 install     puts the app on the pretend phone
#        .\android.ps1 pictures D:\some\folder   copies the pictures of a folder into the pretend phone's gallery
#        .\android.ps1 pair "regista://pair?..."   opens the app on the pretend phone with a pairing link
#        .\android.ps1 screen out.png            saves what the pretend phone is showing
#        .\android.ps1 adb ...     any adb command on the pretend phone
#        .\android.ps1 stop        turns the pretend phone off
#        .\android.ps1 tablet [info|install|pictures <folder>|pair "<link>"|screen <file>|adb ...]
#                                  the same on a real phone or tablet through its cable, with USB debugging on
# The first time it builds the image with the tools (android\tools\Dockerfile): about 1.3 GB to download.
# The pretend phone reaches Regista's door for the phones at 10.0.2.2, port 8443.
param([Parameter(Position = 0)][string]$What = 'build', [Parameter(Position = 1, ValueFromRemainingArguments)][string[]]$More = @())

$project = Join-Path $PSScriptRoot 'android'
function Stop-Run($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }

docker image inspect regista-android 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker build -t regista-android (Join-Path $project 'tools')
    if ($LASTEXITCODE -ne 0) { Stop-Run 'building the image with the Android tools' }
}

switch ($What) {
    'build' {
        # The phone's own screen, built from web/, and the table of places: both travel inside the app,
        # which then finds pictures by day and by place with no computer and no network.
        & (Join-Path $PSScriptRoot 'npm.ps1') run build:telefono
        if ($LASTEXITCODE -ne 0) { Stop-Run 'building the phone screen' }
        $assets = Join-Path $project 'app\src\main\assets'
        $screen = Join-Path $assets 'telefono'
        if (Test-Path $screen) { Remove-Item -LiteralPath $screen -Recurse -Force }
        New-Item -ItemType Directory -Force (Join-Path $assets 'places') | Out-Null
        Copy-Item -Recurse (Join-Path $PSScriptRoot 'web\dist-telefono') $screen
        Copy-Item (Join-Path $PSScriptRoot 'data\geonames\cities15000.zip') (Join-Path $assets 'places\cities15000.zip')
        $preview = Join-Path $assets 'commands'
        $commandFiles = 'commands.onnx', 'commands.json'
        if ($env:REGISTA_COMMAND_BUNDLE) {
            $bundle = $env:REGISTA_COMMAND_BUNDLE
            foreach ($name in $commandFiles) {
                if (-not (Test-Path -LiteralPath (Join-Path $bundle $name) -PathType Leaf)) {
                    Stop-Run "missing $name in the command model bundle"
                }
            }
            New-Item -ItemType Directory -Force $preview | Out-Null
            foreach ($name in $commandFiles) {
                Copy-Item -LiteralPath (Join-Path $bundle $name) -Destination (Join-Path $preview $name) -Force
            }
        } else {
            # Remove only generated preview files, so the next ordinary APK leaves out the experiment.
            foreach ($name in $commandFiles) {
                $generated = Join-Path $preview $name
                if (Test-Path -LiteralPath $generated -PathType Leaf) { Remove-Item -LiteralPath $generated }
            }
        }
        # the key is made once and kept out of the repository: with a new key at each build a phone would refuse the update
        $script = 'mkdir -p .keys && { [ -f .keys/regista.keystore ] || keytool -genkeypair -keystore .keys/regista.keystore -storepass regista -keypass regista -alias regista -keyalg RSA -keysize 2048 -validity 10000 -dname CN=Regista; } && gradle --no-daemon -q assembleRelease'
        docker run --rm -v "${project}:/work" -v regista-gradle:/root/.gradle regista-android sh -c $script
        if ($LASTEXITCODE -ne 0) { Stop-Run 'the build' }
        Write-Host "App: $(Join-Path $project 'app\build\outputs\apk\release\app-arm64-v8a-release.apk') (for almost every phone; the others are beside it)" -ForegroundColor Green
    }
    'phone' {
        docker rm -f regista-phone 2>$null | Out-Null
        $avd = if ($More -and $More[0] -eq '13') { 'regista13' } else { 'regista' }
        $start = "python3 /work/tools/forward.py 8443 host.docker.internal 8443 & exec emulator -avd $avd -no-window -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect -no-metrics -memory 2048"
        docker run -d --name regista-phone --device /dev/kvm -v "${project}:/work" regista-android sh -c $start | Out-Null
        if ($LASTEXITCODE -ne 0) { Stop-Run 'starting the pretend phone' }
        foreach ($attempt in 1..90) {
            if ((docker exec regista-phone adb shell getprop sys.boot_completed 2>$null) -match '1') { break }
            Start-Sleep -Seconds 2
        }
        Write-Host "The pretend phone is on (Android $(docker exec regista-phone adb shell getprop ro.build.version.release))." -ForegroundColor Green
    }
    'install' {
        # the file of the kind of phone the pretend one is
        $kind = (docker exec regista-phone adb shell getprop ro.product.cpu.abi).Trim()
        docker exec regista-phone adb install -r "/work/app/build/outputs/apk/release/app-$kind-release.apk"
    }
    'pictures' {
        if (-not $More -or -not (Test-Path $More[0] -PathType Container)) { Stop-Run 'give the folder with the pictures' }
        docker exec regista-phone mkdir -p /tmp/pictures
        docker cp "$((Resolve-Path $More[0]).Path)\." regista-phone:/tmp/pictures
        # into the folder where a camera puts them, and then Android is told to look: it is its list the app reads
        docker exec regista-phone sh -c 'adb shell mkdir -p /sdcard/DCIM/Camera && adb push /tmp/pictures/. /sdcard/DCIM/Camera/ > /dev/null && adb shell content call --uri content://media/ --method scan_volume --arg external_primary > /dev/null'
        Write-Host 'Pictures copied into the gallery of the pretend phone.' -ForegroundColor Green
    }
    'pair' {
        if (-not $More) { Stop-Run 'give the link shown on the page' }
        docker exec regista-phone adb shell am start -a android.intent.action.VIEW -d "'$($More[0])'" app.regista
    }
    'screen' {
        $target = if ($More) { $More[0] } else { 'phone.png' }
        docker exec regista-phone sh -c 'adb exec-out screencap -p > /tmp/screen.png'
        docker cp regista-phone:/tmp/screen.png $target
        Write-Host "Saved $target" -ForegroundColor Green
    }
    'adb' { docker exec regista-phone adb @More }
    'stop' { docker rm -f regista-phone | Out-Null }
    'tablet' {
        # A real device, through its cable. The adb of the pretend phone lives in Docker, which cannot see
        # USB: this is Google's adb for Windows (platform-tools), downloaded once into android\.tools.
        $adb = Join-Path $project '.tools\platform-tools\adb.exe'
        if (-not (Test-Path $adb)) { Stop-Run "Google's platform-tools for Windows are not in android\.tools" }
        $action = if ($More) { $More[0] } else { 'info' }
        $rest = @($More | Select-Object -Skip 1)
        switch ($action) {
            'info' {
                & $adb devices -l
                Write-Host "Android $(& $adb shell getprop ro.build.version.release), $(& $adb shell getprop ro.product.manufacturer) $(& $adb shell getprop ro.product.model), $(& $adb shell getprop ro.product.cpu.abi)"
            }
            'install' {
                # the file made for the kind of processor the device has
                $kind = (& $adb shell getprop ro.product.cpu.abi).Trim()
                $file = Join-Path $project "app\build\outputs\apk\release\app-$kind-release.apk"
                if (-not (Test-Path $file)) { Stop-Run "no app made for '$kind' devices" }
                & $adb install -r $file
            }
            'pictures' {
                # into an album of their own: what a trial touches is never one of the owner's pictures
                if (-not $rest -or -not (Test-Path $rest[0] -PathType Container)) { Stop-Run 'give the folder with the pictures' }
                & $adb shell mkdir -p "'/sdcard/Pictures/Regista prova'"
                Get-ChildItem $rest[0] -File | ForEach-Object { & $adb push $_.FullName "/sdcard/Pictures/Regista prova/$($_.Name)" | Out-Null }
                # then Android is told to look: Android 10 and later at the whole storage, older ones file by file
                if ([int](& $adb shell getprop ro.build.version.sdk) -ge 29) {
                    & $adb shell content call --uri content://media/ --method scan_volume --arg external_primary | Out-Null
                } else {
                    Get-ChildItem $rest[0] -File | ForEach-Object { & $adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "'file:///sdcard/Pictures/Regista prova/$($_.Name)'" | Out-Null }
                }
                Write-Host 'Pictures copied into the album "Regista prova" of the device.' -ForegroundColor Green
            }
            'pair' { & $adb shell am start -a android.intent.action.VIEW -d "'$($rest[0])'" app.regista }
            'screen' {
                $target = if ($rest) { $rest[0] } else { 'tablet.png' }
                # not in the shared storage, where the gallery would take it for a picture
                & $adb shell screencap -p /data/local/tmp/regista-screen.png
                & $adb pull /data/local/tmp/regista-screen.png $target | Out-Null
                & $adb shell rm /data/local/tmp/regista-screen.png
                Write-Host "Saved $target" -ForegroundColor Green
            }
            'adb' { & $adb @rest }
            default { Stop-Run "unknown tablet command '$action': info, install, pictures, pair, screen, adb" }
        }
    }
    default { Stop-Run "unknown command '$What': build, phone, install, pictures, pair, screen, adb, stop, tablet" }
}
