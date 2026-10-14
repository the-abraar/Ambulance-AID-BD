package bd.ambulanceaid.driver

import bd.ambulanceaid.driver.ShiftWatch.Act
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShiftWatchTest {
    @Test fun aNewMissionRingsOnceWhileTheAppIsOffScreen() {
        val w = ShiftWatch()
        assertEquals(Act.CLEAR, w.poll(404, null, null, acked = false, onScreen = false)) // no mission
        assertFalse(w.onMission)
        assertEquals(Act.ALERT, w.poll(200, "m1", "DISPATCHED", acked = false, onScreen = false))
        assertTrue(w.onMission) // pings go back to the mission rate at once
        assertEquals(Act.NONE, w.poll(200, "m1", "DISPATCHED", acked = false, onScreen = false)) // once, not every poll
        assertEquals(Act.CLEAR, w.poll(200, "m1", "DISPATCHED", acked = true, onScreen = false)) // accepted
        assertEquals(Act.CLEAR, w.poll(200, "m1", "COMPLETED", acked = true, onScreen = false))
        assertFalse(w.onMission) // the 10 minutes after a mission ends are not a mission
        assertEquals(Act.ALERT, w.poll(200, "m2", "DISPATCHED", acked = false, onScreen = false)) // the next one rings
    }

    @Test fun onScreenThePageAlertsAndTheServiceWaits() {
        val w = ShiftWatch()
        assertEquals(Act.NONE, w.poll(200, "m1", "DISPATCHED", acked = false, onScreen = true))
        assertEquals(Act.ALERT, w.poll(200, "m1", "DISPATCHED", acked = false, onScreen = false)) // left without accepting
    }

    @Test fun cancelledBeforeAcceptClearsAndNoAnswerKeepsTheMode() {
        val w = ShiftWatch()
        w.poll(200, "m1", "EN_ROUTE_PICKUP", acked = true, onScreen = false)
        assertEquals(Act.NONE, w.poll(-1, null, null, acked = false, onScreen = false)) // offline
        assertEquals(Act.NONE, w.poll(503, null, null, acked = false, onScreen = false))
        assertTrue(w.onMission)
        assertEquals(Act.CLEAR, w.poll(200, "m1", "CANCELLED", acked = false, onScreen = false))
        assertFalse(w.onMission)
    }

    @Test fun signedOutStopsTheShift() {
        assertEquals(Act.STOP, ShiftWatch().poll(401, null, null, acked = false, onScreen = false))
    }
}
