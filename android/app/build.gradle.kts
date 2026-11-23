plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "app.regista"
    compileSdk = 35
    // the tools that are already in the image: without this line Gradle downloads another version at every build
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "app.regista"
        // Android 7: what older Android lacks (small copies, the original of a picture, its own trash, ...)
        // is done another way, or said to the user; moving pictures to the trash needs Android 11
        minSdk = 24
        targetSdk = 35
        // A larger number at every build, the minutes since 2026 began: a phone takes from the computer an app
        // with a larger one than its own, with no cable (Update.kt). The last number set by hand was 3.
        versionCode = (System.currentTimeMillis() / 60_000 - 29_453_760).toInt()
        versionName = "0.11.1"
    }

    // One app file for each kind of phone; photo models stay on the PC.
    // arm64-v8a for almost every phone and tablet, armeabi-v7a for older 32-bit ones, x86_64 for the emulator.
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = false
        }
    }
    packaging {
        // the engine compressed inside the file, which is then less than half as large to send; the phone unpacks it when it installs the app
        jniLibs {
            useLegacyPackaging = true
        }
    }

    signingConfigs {
        // One key for every build made on this PC, kept out of the repository (android.ps1 makes it):
        // with a new key at each build the phone would refuse to update the app.
        getByName("debug") {
            storeFile = rootProject.file(".keys/regista.keystore")
            storePassword = "regista"
            keyAlias = "regista"
            keyPassword = "regista"
        }
    }

    buildTypes {
        // The app a phone gets is this one, not the "debug" one: from a debug app, whoever has the phone
        // unlocked and a cable can read what the app keeps, the key that lets it into the computer included.
        getByName("release") {
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    // Photo models run only on the PC; no neural runtime is shipped to the phone.
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    testImplementation("junit:junit:4.13.2")
}
