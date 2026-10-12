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
        // Android 10: the first with the calls this app uses to read small copies of pictures
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "0.1"
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
