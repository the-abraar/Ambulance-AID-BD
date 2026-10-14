package bd.ambulanceaid.driver

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Foreground location service: posts the vehicle's GPS fixes to the backend while the WebView is backgrounded or the
 * screen is off, during a mission and, on shift, between missions (where it also polls for new missions and raises
 * the alert). Started only from the visible app (AmbulanceNative.startTracking), so it needs no background location.
 */
class TrackingService : Service() {
    private data class Session(val baseUrl: String, val token: String, val vehicleId: String, val shift: Boolean)

    private val thread = HandlerThread("tracking").apply { start() }
    private val worker = Handler(thread.looper) // queue, session, watch and HTTP are only touched on this thread
    private val queue = PingQueue()
    private val watch = ShiftWatch()
    private var session: Session? = null
    private var pumpScheduled = false
    private var listening = false
    private lateinit var wakeLock: PowerManager.WakeLock

    private val listener = object : LocationListener {
        override fun onLocationChanged(l: Location) = onFix(l)
        // Android 10 and older have no default bodies for these: leaving them out crashes with AbstractMethodError.
        override fun onProviderEnabled(provider: String) {}
        override fun onProviderDisabled(provider: String) {}
        @Deprecated("Deprecated in API 29") override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    }
    private val pump = Runnable { pump() }
    private val poll = Runnable { poll() }

    override fun onBind(intent: Intent?) = null

    override fun onCreate() {
        super.onCreate()
        // The CPU sleeps with the screen off; without this, scheduled retries, polls and HTTP sends stall until the next GPS wake.
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ambulance:tracking").apply { setReferenceCounted(false) }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.channel_tracking), NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(NotificationChannel(MISSION_CHANNEL, getString(R.string.channel_missions), NotificationManager.IMPORTANCE_HIGH).apply {
            val sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
            setSound(sound, AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build()) // rings in silent mode too
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 600, 300, 600)
        })
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // A restart by the system after it killed the app runs in the background, where Android gives a location
        // service no fixes (Android 11-13) or refuses it (14+). Do not run blind: ask the driver to open the app.
        if (flags and (START_FLAG_REDELIVERY or START_FLAG_RETRY) != 0) {
            notifyRestart()
            stopSelf()
            return START_NOT_STICKY
        }
        val s = intent?.let {
            Session(it.getStringExtra(EXTRA_BASE).orEmpty(), it.getStringExtra(EXTRA_TOKEN).orEmpty(),
                it.getStringExtra(EXTRA_VEHICLE).orEmpty(), it.getBooleanExtra(EXTRA_SHIFT, false))
        }
        if (s == null || s.token.isEmpty() || s.vehicleId.isEmpty()) { stopSelf(); return START_NOT_STICKY }
        val granted = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        try { // startForeground first even when refusing: a started foreground service that skips it crashes the app
            val n = notification(s)
            if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            else startForeground(NOTIFICATION_ID, n)
        } catch (e: Exception) { // e.g. a start from the background on Android 12+, or location permission revoked
            Log.w(TAG, "cannot start foreground", e)
            stopWith(0, if (granted) "start-failed" else "no-location-permission")
            return START_NOT_STICKY
        }
        if (!granted) { stopWith(0, "no-location-permission"); return START_NOT_STICKY } // never claim to track without it
        running = true
        wakeLock.acquire(WAKE_TIMEOUT_MS)
        val onMission = intent?.getStringExtra(EXTRA_MISSION).orEmpty().isNotEmpty()
        worker.post {
            if (session?.vehicleId != s.vehicleId) queue.clear() // queued fixes belong to the old vehicle
            session = s // same vehicle with a new token (rotation): keep the queue
            watch.onMission = onMission // what the page knew; the poll keeps it current from here
            mode()
            worker.removeCallbacks(poll)
            if (s.shift) worker.post(poll)
            kick()
        }
        return START_REDELIVER_INTENT // after a kill the system redelivers it, and the branch above asks for the app
    }

    override fun onDestroy() {
        running = false
        (getSystemService(LOCATION_SERVICE) as LocationManager).removeUpdates(listener)
        thread.quitSafely()
        if (wakeLock.isHeld) wakeLock.release()
        cancelAlert(this) // shift ended or the service stopped: a stale alert must not keep ringing
        super.onDestroy()
    }

    /** Mission: a fix every 5-10 s. On shift between missions: one a minute. Re-registers GPS when that changes. */
    private fun mode() {
        val free = session?.shift == true && !watch.onMission
        if (listening && free == queue.free) return
        queue.free = free
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        lm.removeUpdates(listener)
        try {
            for (p in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
                if (p in lm.allProviders) lm.requestLocationUpdates(p, queue.minGapMs, 0f, listener, thread.looper)
            }
        } catch (e: SecurityException) { // permission revoked while running
            return stopWith(0, "no-location-permission")
        }
        listening = true
    }

    private fun onFix(l: Location) {
        if (!l.hasAccuracy()) return
        val ageMs = (SystemClock.elapsedRealtimeNanos() - l.elapsedRealtimeNanos) / 1_000_000
        // Phone clock for ts (not l.time, which is GPS time): the server compares it with sent_at from the same clock.
        val f = Fix(l.latitude, l.longitude, l.accuracy, System.currentTimeMillis() - ageMs, l.elapsedRealtimeNanos / 1_000_000)
        if (queue.offer(f)) { wakeLock.acquire(WAKE_TIMEOUT_MS); kick() }
    }

    private fun kick() {
        if (!pumpScheduled) { pumpScheduled = true; worker.post(pump) }
    }

    private fun pump() {
        pumpScheduled = false
        val s = session ?: return
        val f = queue.next(SystemClock.elapsedRealtime()) ?: return
        val status = http(s, "POST", pingUrl(s.baseUrl, s.vehicleId), pingJson(f, SystemClock.elapsedRealtime(), s.shift)).first
        val wait = queue.result(status)
        if (wait == PingQueue.STOP) return stopWith(status, "rejected")
        if (queue.size > 0) { pumpScheduled = true; worker.postDelayed(pump, wait) }
    }

    /** On shift: every 30 s, is there a new mission? The page cannot tell: Android freezes it in the background. */
    private fun poll() {
        val s = session?.takeIf { it.shift } ?: return
        val (status, body) = http(s, "GET", originOf(s.baseUrl) + "/missions/current", null)
        val m = if (status == 200) runCatching { JSONObject(body.orEmpty()) }.getOrNull() else null
        when (watch.poll(status, m?.optString("mission_id"), m?.optString("status"), m?.isNull("acknowledged_at") == false, appOnScreen)) {
            ShiftWatch.Act.STOP -> return stopWith(status, "rejected")
            ShiftWatch.Act.ALERT -> alert(m?.optString("pickup_address").orEmpty())
            ShiftWatch.Act.CLEAR -> cancelAlert(this)
            ShiftWatch.Act.NONE -> {}
        }
        mode()
        wakeLock.acquire(WAKE_TIMEOUT_MS)
        worker.postDelayed(poll, POLL_MS)
    }

    /** HTTP status (or -1 when there is no answer: offline, timeout, DNS) and, for a 200, the body. */
    private fun http(s: Session, method: String, url: String, body: String?): Pair<Int, String?> = try {
        (URL(url).openConnection() as HttpURLConnection).run {
            try {
                requestMethod = method
                connectTimeout = 10_000
                readTimeout = 15_000
                setRequestProperty("Authorization", "Bearer ${s.token}")
                if (body != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    outputStream.use { it.write(body.toByteArray()) }
                }
                val code = responseCode
                code to (if (code == 200) inputStream.bufferedReader().use { it.readText() } else null)
            } finally { disconnect() }
        }
    } catch (e: Exception) {
        -1 to null
    }

    /** Stops for good and tells the page (MainActivity turns this into the `ambulance-native-stopped` DOM event). */
    private fun stopWith(status: Int, reason: String) {
        Log.i(TAG, "stopping: $reason $status")
        running = false
        onStopped?.invoke(status, reason)
        stopSelf()
    }

    private fun openApp() = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)

    private fun notification(s: Session): Notification = Notification.Builder(this, CHANNEL)
        .setSmallIcon(R.drawable.ic_cross)
        .setContentTitle(getString(R.string.tracking_title, s.vehicleId))
        .setContentText(getString(if (s.shift) R.string.shift_text else R.string.tracking_text))
        .setContentIntent(openApp())
        .setOngoing(true)
        .build()

    /** The new-mission alert for a phone in a pocket: alarm sound and vibration, repeated until the driver opens it. */
    private fun alert(address: String) {
        val n = Notification.Builder(this, MISSION_CHANNEL)
            .setSmallIcon(R.drawable.ic_cross)
            .setContentTitle(getString(R.string.mission_title))
            .setContentText(address.ifEmpty { getString(R.string.mission_text) })
            .setCategory(Notification.CATEGORY_ALARM)
            .setContentIntent(openApp())
            .setAutoCancel(true)
            .build()
        n.flags = n.flags or Notification.FLAG_INSISTENT
        getSystemService(NotificationManager::class.java).notify(ALERT_ID, n)
    }

    private fun notifyRestart() {
        getSystemService(NotificationManager::class.java).notify(RESTART_ID, Notification.Builder(this, MISSION_CHANNEL)
            .setSmallIcon(R.drawable.ic_cross)
            .setContentTitle(getString(R.string.restart_title))
            .setContentText(getString(R.string.restart_text))
            .setContentIntent(openApp())
            .setAutoCancel(true)
            .build())
    }

    companion object {
        private const val TAG = "TrackingService"
        private const val CHANNEL = "tracking"
        private const val MISSION_CHANNEL = "missions"
        private const val NOTIFICATION_ID = 1
        private const val ALERT_ID = 2
        private const val RESTART_ID = 3
        private const val WAKE_TIMEOUT_MS = 10 * 60_000L // renewed on every queued fix and poll; lapses if both go silent
        private const val POLL_MS = 30_000L
        const val EXTRA_BASE = "baseUrl"
        const val EXTRA_TOKEN = "token"
        const val EXTRA_VEHICLE = "vehicleId"
        const val EXTRA_MISSION = "missionId"
        const val EXTRA_SHIFT = "shift"

        /** True from a successful start until stop; read by AmbulanceNative.isTracking(). */
        @Volatile var running = false
            private set

        /** Set by MainActivity: while it is on screen the page alerts itself, so the service does not. */
        @Volatile var appOnScreen = false

        /** Set by MainActivity; called on any thread with (HTTP status or 0, reason). */
        @Volatile var onStopped: ((Int, String) -> Unit)? = null

        fun start(c: Context, baseUrl: String, token: String, vehicleId: String, missionId: String, shift: Boolean) {
            c.startForegroundService(Intent(c, TrackingService::class.java)
                .putExtra(EXTRA_BASE, baseUrl).putExtra(EXTRA_TOKEN, token).putExtra(EXTRA_VEHICLE, vehicleId)
                .putExtra(EXTRA_MISSION, missionId).putExtra(EXTRA_SHIFT, shift))
            running = true // set now, not in onStartCommand, so isTracking() right after startTracking() is already true
        }

        fun stop(c: Context) { running = false; c.stopService(Intent(c, TrackingService::class.java)) }

        fun cancelAlert(c: Context) = c.getSystemService(NotificationManager::class.java).cancel(ALERT_ID)
    }
}
