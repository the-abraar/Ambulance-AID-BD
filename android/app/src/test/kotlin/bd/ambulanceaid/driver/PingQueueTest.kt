package bd.ambulanceaid.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

class PingQueueTest {
    private val t0 = 1_000_000L
    private fun fix(sec: Long, lat: Double = 23.8103, acc: Float = 10f) =
        Fix(lat, 90.4125, acc, 1_760_000_000_000L + sec * 1000, t0 + sec * 1000)

    @Test fun dropsInaccurateFixes() {
        val q = PingQueue()
        assertFalse(q.offer(fix(0, acc = 100.5f)))
        assertTrue(q.offer(fix(0, acc = 100f)))
    }

    @Test fun samplesEvery10sWhenStillAnd5sWhenMoving() {
        val q = PingQueue()
        assertTrue(q.offer(fix(0)))
        assertFalse(q.offer(fix(4, lat = 23.9))) // moved, but under 5 s
        assertFalse(q.offer(fix(6))) // still, under 10 s
        assertTrue(q.offer(fix(6, lat = 23.8105))) // ~22 m after 6 s
        assertFalse(q.offer(fix(15, lat = 23.8105)))
        assertTrue(q.offer(fix(16, lat = 23.8105))) // 10 s, not moved
        assertEquals(3, q.size)
    }

    @Test fun samplesOnceAMinuteBetweenMissions() {
        val q = PingQueue()
        q.free = true
        assertEquals(PingQueue.FREE_GAP_MS, q.minGapMs) // TrackingService asks GPS for this rate too
        assertTrue(q.offer(fix(0)))
        assertFalse(q.offer(fix(30, lat = 23.9))) // moved far, but under a minute
        assertTrue(q.offer(fix(60)))
        q.free = false // a mission arrived: back to 5-10 s
        assertTrue(q.offer(fix(70)))
        assertEquals(PingQueue.MIN_GAP_MS, q.minGapMs)
    }

    @Test fun keepsOrderAndDropsWhatTheServerCallsTooOld() {
        val q = PingQueue()
        q.offer(fix(0)); q.offer(fix(10)); q.offer(fix(20))
        assertEquals(fix(0), q.next(t0 + 290_000))
        assertEquals(fix(10), q.next(t0 + 295_000)) // the 0 s fix is now over 290 s old
        assertEquals(2, q.size)
        assertNull(q.next(t0 + 320_000))
        assertEquals(0, q.size)
    }

    @Test fun capsTheQueue() {
        val q = PingQueue()
        for (i in 0..PingQueue.MAX_QUEUE.toLong()) q.offer(fix(i * 10))
        assertEquals(PingQueue.MAX_QUEUE, q.size)
        assertEquals(fix(10), q.next(t0 + 10_000))
    }

    @Test fun serverAnswers() {
        val q = PingQueue()
        q.offer(fix(0)); q.offer(fix(10)); q.offer(fix(20)); q.offer(fix(30))
        assertEquals(PingQueue.SPACING_MS, q.result(201)); assertEquals(3, q.size)
        assertEquals(PingQueue.RATE_WAIT_MS, q.result(429)); assertEquals(3, q.size) // kept, retried
        assertEquals(PingQueue.SPACING_MS, q.result(422)); assertEquals(2, q.size) // refused for good: dropped
        assertEquals(2_000L, q.result(-1)); assertEquals(4_000L, q.result(503)); assertEquals(8_000L, q.result(408))
        assertEquals(2, q.size) // kept through outages
        repeat(10) { q.result(-1) }
        assertEquals(PingQueue.MAX_BACKOFF_MS, q.result(-1))
        q.result(200)
        assertEquals(2_000L, q.result(-1)) // success resets the backoff
        for (s in listOf(401, 403, 404)) assertEquals(PingQueue.STOP, q.result(s))
    }

    @Test fun clearForgetsTheLastFixToo() {
        val q = PingQueue()
        q.offer(fix(0)); q.clear()
        assertTrue(q.offer(fix(1)))
    }

    @Test fun requestJsonMatchesTheSpecAndIgnoresLocale() {
        val saved = Locale.getDefault()
        try {
            Locale.setDefault(Locale.forLanguageTag("bn-BD")) // Bengali digits must not leak into the body
            val f = Fix(23.8103, 90.4125, 12.5f, 1_760_000_000_123L, t0)
            assertEquals(
                """{"lat":23.8103,"lng":90.4125,"ts":"2025-10-09T08:53:20.123Z","sent_at":"2025-10-09T08:53:50.123Z","accuracy":12.5}""",
                pingJson(f, t0 + 30_000), // sent 30 s after the fix: the server reads a 30 s age
            )
        } finally { Locale.setDefault(saved) }
    }

    @Test fun onShiftPingsSayTheyAre() {
        val f = Fix(23.8103, 90.4125, 12.5f, 1_760_000_000_123L, t0)
        assertTrue(pingJson(f, t0, onShift = true).endsWith(""","accuracy":12.5,"on_shift":true}"""))
    }

    @Test fun urls() {
        assertEquals("http://10.0.2.2:8000/vehicles/v%201%2F2/pings", pingUrl("http://10.0.2.2:8000/driver/", "v 1/2"))
        assertEquals("https://amb.example.org", originOf("https://amb.example.org/driver/?x=1"))
    }

    @Test fun distance() {
        val d = distanceM(fix(0, lat = 23.0), fix(0, lat = 24.0))
        assertTrue(d in 111_000.0..111_400.0)
    }
}
