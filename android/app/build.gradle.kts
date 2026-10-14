import java.util.Properties

plugins {
    id("com.android.application") version "9.0.1" // AGP 9 compiles Kotlin itself: no Kotlin plugin needed
}

// The driver web app URL: -Pambulance.baseUrl=... or `ambulance.baseUrl=...` in android/local.properties.
val localProps = Properties().apply {
    rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}
val baseUrlProp = (findProperty("ambulance.baseUrl") as String?) ?: localProps.getProperty("ambulance.baseUrl")
val devUrl = "http://10.0.2.2:8000/driver/" // the host machine as seen from the Android emulator

android {
    namespace = "bd.ambulanceaid.driver"
    compileSdk = 36

    defaultConfig {
        applicationId = "bd.ambulanceaid.driver"
        minSdk = 26 // notification channels and startForegroundService exist from 26; Android 7 is under 2% of phones
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    buildFeatures { buildConfig = true }

    buildTypes {
        debug {
            buildConfigField("String", "BASE_URL", "\"${baseUrlProp ?: devUrl}\"")
        }
        release {
            // Release must be HTTPS and must name its host; there is no default. Signing is the owner's (see docs/android-wrapper.md).
            buildConfigField("String", "BASE_URL", "\"${baseUrlProp.orEmpty()}\"")
        }
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}

val releaseUrl = baseUrlProp.orEmpty()
tasks.matching { it.name == "preReleaseBuild" }.configureEach {
    doFirst {
        require(releaseUrl.startsWith("https://")) { "Set ambulance.baseUrl to the HTTPS driver app URL for a release build (got '$releaseUrl')" }
    }
}
