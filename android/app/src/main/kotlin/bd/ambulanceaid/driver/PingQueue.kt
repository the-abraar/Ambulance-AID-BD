package bd.ambulanceaid.driver

import java.net.URL
import java.net.URLEncoder
import java.time.Instant
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/** One GPS fix. [wallMs] is the phone clock (the server tolerates skew); [elapsedMs] is the monotonic clock for its age. */
data class Fix(val lat: Double, val lng: Double, val accuracy: Float, val wallMs: Long, val elapsedMs: Long)

/**
 * Ordered offline queue of pings with the server's drop rules (POST /vehicles/{id}/pings in docs/api-spec/openapi.yaml).
 * Not thread-safe: TrackingService uses it from its one worker thread.
 */
class PingQueue {
    private val q = ArrayDeque<Fix>()
    private var last: Fix? = null
    private var backoffMs = 0L
    val size get() = q.size

    /** Queues a fix if it is accurate enough and 5 s after the last one, and either moved 20 m or is 10 s newer. */
    fun offer(f: Fix): Boolean {
        if (f.accuracy > MAX_ACCURACY_M) return false
        last?.let { p ->
            val dt = f.elapsedMs - p.elapsedMs
            if (dt < MIN_GAP_MS || (dt < IDLE_GAP_MS && distanceM(p, f) < MOVE_M)) return false
        }
        last = f
        q.addLast(f)
        if (q.size > MAX_QUEUE) q.removeFirst()
        return true
    }

    /** The oldest fix to send, after dropping those the server would refuse as older than 300 s. */
    fun next(nowElapsedMs: Long): Fix? {
        while (q.isNotEmpty() && nowElapsedMs - q.first().elapsedMs > MAX_AGE_MS) q.removeFirst()
        return q.firstOrNull()
    }

    /** Applies the HTTP status (or -1 for no answer) for the head fix; returns ms to wait before the next send, or [STOP]. */
    fun result(status: Int): Long = when {
        status in 200..299 -> drop()
        status == 401 || status == 403 || status == 404 -> STOP // token revoked, or no active mission for this vehicle
        status == 429 -> RATE_WAIT_MS
        status in 400..499 && status != 408 -> drop() // 422: (0,0), too old or impossible jump; retrying cannot help
        else -> { backoffMs = (backoffMs * 2).coerceIn(MIN_BACKOFF_MS, MAX_BACKOFF_MS); backoffMs }
    }

    fun clear() { q.clear(); last = null; backoffMs = 0 }

    private fun drop(): Long { q.removeFirstOrNull(); backoffMs = 0; return SPACING_MS }

    companion object {
        const val STOP = -1L
        const val MAX_ACCURACY_M = 100f
        const val MIN_GAP_MS = 5_000L
        const val IDLE_GAP_MS = 10_000L
        const val MOVE_M = 20.0
        const val MAX_AGE_MS = 290_000L // server refuses > 300 s; sent_at is set at send time, so 10 s spare is plenty
        const val MAX_QUEUE = 100 // 300 s / 5 s = 60 fixes can still be accepted; cap anyway
        const val SPACING_MS = 1_100L // server allows one ping per second per vehicle
        const val RATE_WAIT_MS = 2_000L
        const val MIN_BACKOFF_MS = 2_000L
        const val MAX_BACKOFF_MS = 60_000L
    }
}

/** Request body for one ping. sent_at - ts is the fix's age on the monotonic clock, so phone clock changes cannot skew it. */
fun pingJson(f: Fix, nowElapsedMs: Long): String {
    val sentAt = Instant.ofEpochMilli(f.wallMs + (nowElapsedMs - f.elapsedMs))
    // Double/Float.toString and Instant.toString ignore the locale, so a Bangla phone still sends ASCII digits.
    return """{"lat":${f.lat},"lng":${f.lng},"ts":"${Instant.ofEpochMilli(f.wallMs)}","sent_at":"$sentAt","accuracy":${f.accuracy}}"""
}

/** scheme://host[:port] of a URL; the API is served at the root of the driver app's origin. */
fun originOf(url: String): String = URL(url).let { "${it.protocol}://${it.authority}" }

fun pingUrl(baseUrl: String, vehicleId: String): String =
    "${originOf(baseUrl)}/vehicles/${URLEncoder.encode(vehicleId, "UTF-8").replace("+", "%20")}/pings"

fun distanceM(a: Fix, b: Fix): Double {
    val r = Math.PI / 180
    val h = sin((b.lat - a.lat) * r / 2).let { it * it } +
        cos(a.lat * r) * cos(b.lat * r) * sin((b.lng - a.lng) * r / 2).let { it * it }
    return 2 * 6_371_000 * asin(sqrt(h))
}
