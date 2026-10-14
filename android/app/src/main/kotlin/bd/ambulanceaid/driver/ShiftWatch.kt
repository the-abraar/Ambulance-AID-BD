package bd.ambulanceaid.driver

/**
 * What the on-shift poll of GET /missions/current means (docs/android-wrapper.md). Plain Kotlin, unit-tested;
 * TrackingService parses the JSON and calls [poll] from its one worker thread.
 */
class ShiftWatch {
    enum class Act { NONE, ALERT, CLEAR, STOP }

    /** True while the driver has an active mission (ping every 5-10 s); false between missions (once a minute). */
    var onMission = false
    private var alerted: String? = null

    /**
     * [http] is the HTTP status (-1: no answer); [status] and [acked] describe the mission on a 200. A new mission not
     * yet accepted raises one alert while the app is off screen (on screen, the page alerts itself). Acceptance or the
     * mission's end clears it. 401 (signed out or revoked) stops the shift.
     */
    fun poll(http: Int, missionId: String?, status: String?, acked: Boolean, onScreen: Boolean): Act {
        if (http == 401) return Act.STOP
        if (http != 200 && http != 404) return Act.NONE // offline or a server error: keep the current mode
        onMission = http == 200 && status != null && status !in ENDED
        val waiting = onMission && !acked
        if (waiting && missionId != alerted && !onScreen) { alerted = missionId; return Act.ALERT }
        return if (waiting) Act.NONE else Act.CLEAR
    }

    companion object {
        /** The state machine's terminal states (backend/app/state_machine.py; a backend test fails on drift). */
        val ENDED = setOf("COMPLETED", "CANCELLED")
    }
}
