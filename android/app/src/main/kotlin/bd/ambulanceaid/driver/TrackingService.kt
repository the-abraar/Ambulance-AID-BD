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
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import java.net.HttpURLConnection
import java.net.URL

/**
 * Foreground location service: posts the vehicle's GPS fixes to the backend while the WebView is backgrounded or the
 * screen is off. Started only from the visible app (AmbulanceNative.startTracking), so it needs no background location.
 */
class TrackingService : Service() {
    private data class Session(val baseUrl: String, val token: String, val vehicleId: String)

    private val thread = HandlerThread("tracking").apply { start() }
    private val worker = Handler(thread.looper) // queue, session and HTTP are only touched on this thread
    private val queue = PingQueue()
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

    override fun onBind(intent: Intent?) = null

    override fun onCreate() {
        super.onCreate()
        // The CPU sleeps with the screen off; without this, scheduled retries and HTTP sends stall until the next GPS wake.
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ambulance:tracking").apply { setReferenceCounted(false) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val s = intent?.let { Session(it.getStringExtra(EXTRA_BASE).orEmpty(), it.getStringExtra(EXTRA_TOKEN).orEmpty(), it.getStringExtra(EXTRA_VEHICLE).orEmpty()) }
        if (s == null || s.token.isEmpty() || s.vehicleId.isEmpty()) { stopSelf(); return START_NOT_STICKY }
        try {
            val n = notification(s.vehicleId)
            if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            else startForeground(NOTIFICATION_ID, n)
        } catch (e: Exception) { // e.g. a restart from the background on Android 12+, or location permission revoked
            Log.w(TAG, "cannot start foreground", e)
            stopWith(0, "start-failed")
            return START_NOT_STICKY
        }
        running = true
        wakeLock.acquire(WAKE_TIMEOUT_MS)
        worker.post {
            if (session?.vehicleId != s.vehicleId) queue.clear() // queued fixes belong to the old vehicle
            session = s // same vehicle with a new token (rotation): keep the queue
            if (!listening) listen()
            kick()
        }
        return START_REDELIVER_INTENT // after a kill, the system redelivers the session intent
    }

    override fun onDestroy() {
        running = false
        (getSystemService(LOCATION_SERVICE) as LocationManager).removeUpdates(listener)
        thread.quitSafely()
        if (wakeLock.isHeld) wakeLock.release()
        super.onDestroy()
    }

    private fun listen() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            return stopWith(0, "no-location-permission")
        }
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        for (p in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
            if (p in lm.allProviders) lm.requestLocationUpdates(p, PingQueue.MIN_GAP_MS, 0f, listener, thread.looper)
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
        val status = post(s, pingJson(f, SystemClock.elapsedRealtime()))
        val wait = queue.result(status)
        if (wait == PingQueue.STOP) return stopWith(status, "rejected")
        if (queue.size > 0) { pumpScheduled = true; worker.postDelayed(pump, wait) }
    }

    /** HTTP status, or -1 when there is no answer (offline, timeout, DNS). */
    private fun post(s: Session, body: String): Int = try {
        (URL(pingUrl(s.baseUrl, s.vehicleId)).openConnection() as HttpURLConnection).run {
            try {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 15_000
                doOutput = true
                setRequestProperty("Authorization", "Bearer ${s.token}")
                setRequestProperty("Content-Type", "application/json")
                outputStream.use { it.write(body.toByteArray()) }
                responseCode
            } finally { disconnect() }
        }
    } catch (e: Exception) {
        -1
    }

    /** Stops for good and tells the page (MainActivity turns this into the `ambulance-native-stopped` DOM event). */
    private fun stopWith(status: Int, reason: String) {
        Log.i(TAG, "stopping: $reason $status")
        running = false
        onStopped?.invoke(status, reason)
        stopSelf()
    }

    private fun notification(vehicleId: String): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.channel_tracking), NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_cross)
            .setContentTitle(getString(R.string.tracking_title, vehicleId))
            .setContentText(getString(R.string.tracking_text))
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "TrackingService"
        private const val CHANNEL = "tracking"
        private const val NOTIFICATION_ID = 1
        private const val WAKE_TIMEOUT_MS = 10 * 60_000L // renewed on every queued fix; lapses if GPS goes silent
        const val EXTRA_BASE = "baseUrl"
        const val EXTRA_TOKEN = "token"
        const val EXTRA_VEHICLE = "vehicleId"

        /** True from a successful start until stop; read by AmbulanceNative.isTracking(). */
        @Volatile var running = false
            private set

        /** Set by MainActivity; called on any thread with (HTTP status or 0, reason). */
        @Volatile var onStopped: ((Int, String) -> Unit)? = null

        fun start(c: Context, baseUrl: String, token: String, vehicleId: String) {
            c.startForegroundService(Intent(c, TrackingService::class.java)
                .putExtra(EXTRA_BASE, baseUrl).putExtra(EXTRA_TOKEN, token).putExtra(EXTRA_VEHICLE, vehicleId))
            running = true // set now, not in onStartCommand, so isTracking() right after startTracking() is already true
        }

        fun stop(c: Context) { running = false; c.stopService(Intent(c, TrackingService::class.java)) }
    }
}
