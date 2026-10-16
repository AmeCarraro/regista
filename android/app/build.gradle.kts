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
        versionCode = 2
        versionName = "0.2"
        // the phones this app is built for: almost every phone and tablet (64 and 32 bit), and the emulator
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
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
    // the engine that runs the two models with which the phone looks at pictures by itself (Microsoft, MIT licence)
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.29.0")
}
