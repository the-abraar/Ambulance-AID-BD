package bd.ambulanceaid.driver

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.webkit.GeolocationPermissions
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.window.OnBackInvokedDispatcher
import org.json.JSONObject

/** Loads the driver web app and exposes `AmbulanceNative` (see docs/android-wrapper.md) for native background tracking. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val appOrigin = originOf(BuildConfig.BASE_URL)
    private val asked = mutableSetOf<String>() // setup steps already offered in this launch
    private var setupOpen = false // a setup dialog or permission request is on screen
    private var pendingGeo: Pair<String, GeolocationPermissions.Callback>? = null
    @Volatile private var resumed = false // read by the bridge on a WebView thread
    private var pendingStop: String? = null
    private val onStopped: (Int, String) -> Unit = { status, reason ->
        runOnUiThread { // reason is one of TrackingService's fixed words, safe to inline
            pendingStop = "window.dispatchEvent(new CustomEvent('ambulance-native-stopped'," +
                "{detail:{status:$status,reason:'$reason'}}))"
            if (resumed) flushStop()
        }
    }

    // A page hidden for long can be frozen and lose the event (seen once on the emulator), so deliver it on screen.
    private fun flushStop() { pendingStop?.let { web.evaluateJavascript(it, null) }; pendingStop = null }

    override fun onResume() {
        super.onResume(); resumed = true; TrackingService.appOnScreen = true
        TrackingService.cancelAlert(this) // the page shows the mission and alerts itself
        flushStop()
    }

    override fun onPause() { resumed = false; TrackingService.appOnScreen = false; super.onPause() }

    @SuppressLint("SetJavaScriptEnabled") // the page is our own driver app; other origins open outside the WebView
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.setGeolocationEnabled(true)
            addJavascriptInterface(Bridge(), "AmbulanceNative")
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                    if (sameOrigin(req.url.toString())) return false
                    try { startActivity(Intent(Intent.ACTION_VIEW, req.url)) } catch (_: ActivityNotFoundException) {}
                    return true // tel:, sms:, Google Maps and any other site open in their own apps
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onGeolocationPermissionsShowPrompt(origin: String, cb: GeolocationPermissions.Callback) {
                    when {
                        !sameOrigin(origin) -> cb.invoke(origin, false, false)
                        granted(Manifest.permission.ACCESS_FINE_LOCATION) -> cb.invoke(origin, true, false)
                        else -> { pendingGeo = origin to cb; askLocationAgain() } // answered when the driver decides
                    }
                }
            }
        }
        val root = FrameLayout(this).apply { setBackgroundColor(Color.BLACK); addView(web) }
        if (Build.VERSION.SDK_INT >= 30) root.setOnApplyWindowInsetsListener { v, insets -> // edge-to-edge is forced from Android 15
            val i = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.ime())
            v.setPadding(i.left, i.top, i.right, i.bottom)
            android.view.WindowInsets.CONSUMED
        }
        setContentView(root)
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT) { back() }
        }
        TrackingService.onStopped = onStopped
        if (savedInstanceState == null) web.loadUrl(link(intent) ?: BuildConfig.BASE_URL) else web.restoreState(savedInstanceState)
        nextSetupStep()
    }

    // singleTask: a pairing QR scanned while the app runs arrives here; the page pairs on the #pair= hash change.
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); link(intent)?.let { web.loadUrl(it) } }

    /** An App Link into the driver app on our own origin (the console's pairing QR), else null. */
    private fun link(i: Intent?) = i?.dataString?.takeIf { sameOrigin(it) }

    override fun onSaveInstanceState(outState: Bundle) { super.onSaveInstanceState(outState); web.saveState(outState) }

    override fun onDestroy() {
        if (TrackingService.onStopped === onStopped) TrackingService.onStopped = null
        web.destroy()
        super.onDestroy()
    }

    @SuppressLint("GestureBackNavigation") // only reached below Android 13; 13+ uses the OnBackInvokedCallback above
    @Deprecated("Android 12 and older")
    override fun onBackPressed() = back()

    private fun back() { if (web.canGoBack()) web.goBack() else moveTaskToBack(true) } // keep the page and tracking alive

    private fun sameOrigin(url: String) = runCatching { originOf(url) }.getOrNull() == appOrigin
    private fun granted(p: String) = checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    /** JS interface. Methods run on a WebView binder thread. */
    inner class Bridge {
        /** json = {baseUrl, token, vehicleId, missionId, shift}. Replaces any running session. False if refused (see docs). */
        @JavascriptInterface
        fun startTracking(json: String): Boolean {
            // Only from the visible app: a location service started in the background gets no fixes (Android 11-13).
            if (!resumed) return false
            val o = runCatching { JSONObject(json) }.getOrNull() ?: return false
            val base = o.optString("baseUrl")
            val token = o.optString("token")
            val vehicle = o.optString("vehicleId")
            // Only our own origin: any other page that ends up in the WebView must not redirect the vehicle's location.
            if (!sameOrigin(base) || vehicle.isEmpty() || token.isEmpty() || token.any { it !in '!'..'~' }) return false
            if (!granted(Manifest.permission.ACCESS_FINE_LOCATION)) {
                runOnUiThread { askLocationAgain() }
                return false
            }
            return try {
                TrackingService.start(this@MainActivity, base, token, vehicle, o.optString("missionId"), o.optBoolean("shift"))
                true
            } catch (e: Exception) { // Android 12+ refuses to start a foreground service while the app is in the background
                false
            }
        }

        @JavascriptInterface
        fun stopTracking() = TrackingService.stop(this@MainActivity)

        @JavascriptInterface
        fun isTracking() = TrackingService.running
    }

    // ---- setup: each permission or setting is explained first, then asked; one dialog at a time.

    private fun nextSetupStep() {
        val fine = Manifest.permission.ACCESS_FINE_LOCATION
        if (!granted(fine) && asked.add("location")) {
            return explain(R.string.why_location) { requestPermissions(arrayOf(fine, Manifest.permission.ACCESS_COARSE_LOCATION), REQ_PERMISSIONS) }
        }
        pendingGeo?.let { (origin, cb) -> cb.invoke(origin, granted(fine), false) } // the web fallback's GPS prompt
        pendingGeo = null
        val oem = Build.MANUFACTURER.lowercase().takeIf { it in setOf("xiaomi", "oppo", "vivo", "realme") }
        val prefs = getPreferences(MODE_PRIVATE)
        setupOpen = true
        when {
            Build.VERSION.SDK_INT >= 33 && !granted(Manifest.permission.POST_NOTIFICATIONS) && asked.add("notifications") ->
                explain(R.string.why_notifications) { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_PERMISSIONS) }
            !getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName) && asked.add("battery") ->
                explain(R.string.why_battery) {
                    @SuppressLint("BatteryLife") // tracking an ambulance on a mission is the app's core function
                    val i = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
                    try { @Suppress("DEPRECATION") startActivityForResult(i, REQ_BATTERY) } catch (_: ActivityNotFoundException) { nextSetupStep() }
                }
            oem != null && !prefs.getBoolean("oemShown", false) && asked.add("oem") -> { // shown once per install
                prefs.edit().putBoolean("oemShown", true).apply()
                AlertDialog.Builder(this).setMessage(R.string.oem_guide)
                    .setPositiveButton(R.string.open_settings) { _, _ ->
                        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
                    }
                    .setNeutralButton(R.string.open_guide) { _, _ ->
                        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://dontkillmyapp.com/$oem"))) } catch (_: ActivityNotFoundException) {}
                    }
                    .setNegativeButton(R.string.not_now, null)
                    .setOnDismissListener { nextSetupStep() }
                    .show()
            }
            else -> setupOpen = false
        }
    }

    /** After a refusal: offer the location step again, now or when the current setup dialog closes. */
    private fun askLocationAgain() { asked.remove("location"); if (!setupOpen) nextSetupStep() }

    private fun explain(message: Int, then: () -> Unit) {
        setupOpen = true
        AlertDialog.Builder(this).setMessage(message).setCancelable(false)
            .setPositiveButton(R.string.continue_) { _, _ -> then() }
            .setNegativeButton(R.string.not_now) { _, _ -> nextSetupStep() }
            .show()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) = nextSetupStep()

    @Deprecated("Platform Activity API; no AndroidX on purpose")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQ_BATTERY) nextSetupStep()
    }

    private companion object {
        const val REQ_PERMISSIONS = 1
        const val REQ_BATTERY = 2
    }
}
