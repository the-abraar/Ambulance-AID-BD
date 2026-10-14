import java.net.URI
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

// The App Link for the console's pairing QR (<BASE_URL>#pair=CODE). An unset release URL fails in preReleaseBuild below;
// the placeholder host only lets Gradle configure.
fun appLink(url: String): Map<String, String> = URI(url.ifEmpty { "https://unset.invalid/driver/" }).let {
    mapOf("appLinkScheme" to it.scheme, "appLinkHost" to it.host, "appLinkPath" to it.path.ifEmpty { "/" })
}

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
            manifestPlaceholders += appLink(baseUrlProp ?: devUrl)
        }
        release {
            // Release must be HTTPS and must name its host; there is no default. Signing is the owner's (see docs/android-wrapper.md).
            buildConfigField("String", "BASE_URL", "\"${baseUrlProp.orEmpty()}\"")
            manifestPlaceholders += appLink(baseUrlProp.orEmpty())
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
