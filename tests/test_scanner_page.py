"""Static checks on the scanner page.

Camera acquisition cannot be exercised in this suite — it needs a real browser
and a real device — so the properties that broke it in the field are asserted
against the template instead. Each of these corresponds to a failure that
reached a phone at an event.
"""

import pathlib
import re

import pytest

SCANNER = pathlib.Path(__file__).resolve().parent.parent / "templates" / "scanner.html"


@pytest.fixture(scope="module")
def source() -> str:
    return SCANNER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script(source) -> str:
    return re.findall(r"<script>(.*?)</script>", source, re.S)[-1]


def strip_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


class TestCameraConstraints:
    def test_no_exact_constraints_anywhere(self, script):
        """`exact` is mandatory per spec: no match means the request is rejected.

        A phone with five lenses often matches none of them exactly, and Brave
        randomises deviceIds to resist fingerprinting, so an exact deviceId can
        never match. This is what produced "Requested device not found" on a
        device that had permission granted and five cameras listed.
        """
        code = strip_comments(script)
        assert "exact" not in code, (
            "an exact constraint reappeared; use a plain or ideal value so the "
            "browser can fall back to the nearest camera"
        )

    def test_attempts_are_spaced_apart(self, script):
        """Android needs a moment after a rejected request.

        Firing the next attempt immediately returns NotFoundError regardless of
        the constraints, which makes one bad first attempt look like the phone
        has no cameras at all.
        """
        code = strip_comments(script)
        assert "pause(" in code, "no delay between camera attempts"

    def test_the_front_camera_is_still_reachable(self, script):
        """As a last resort, not as an early fallback.

        It is ranked lowest in the device list rather than requested by a
        dedicated constraint, so it is only ever reached once every rear lens
        has refused — and {video:true} can still land on it on a first run,
        before labels exist.
        """
        code = strip_comments(script)
        assert "front|face|user|self" in code
        assert re.search(r"\{\s*video:\s*true\s*\}", code)

    def test_tries_plain_video_true(self, script):
        assert re.search(r"\{\s*video:\s*true\s*\}", script)

    def test_checks_the_track_is_live(self, script):
        """A stream can return with no track, or one already ended."""
        assert "readyState === 'live'" in script

    def test_releases_streams_it_cannot_use(self, script):
        assert "releaseStream" in script

    def test_permission_refusal_short_circuits(self, script):
        assert "NotAllowedError" in script


class TestCameraSelection:
    """The scanner must land on a rear lens, and let the operator override it.

    Reported from the field: it opened the *front* camera. A bare {video:true}
    returns the browser default, which on a phone is usually the selfie camera,
    and it was being tried before the device list was consulted.
    """

    def test_device_list_is_consulted_before_video_true(self, script):
        code = strip_comments(script)
        by_device = code.index("enumerateDevices")
        video_true = code.index("video: true")
        assert by_device < video_true, (
            "{video:true} is tried before the camera list; it returns the "
            "browser default, which is usually the front camera"
        )

    def test_rear_cameras_rank_above_front(self, script):
        assert "rankCamera" in script
        code = strip_comments(script)
        assert "back|rear|environment" in code
        assert "front|face|user|self" in code

    def test_secondary_lenses_rank_below_the_main_rear(self, script):
        """Ultrawide, macro and depth sensors often cannot produce video."""
        assert "wide|ultra|macro|depth|tele|mono" in strip_comments(script)

    def test_choice_is_remembered(self, script):
        assert "scanner-camera-id" in script
        assert "rememberCamera" in script

    def test_a_switcher_is_offered(self, source, script):
        assert 'id="btn-switch"' in source
        assert 'id="cam-list"' in source
        assert "renderCameraChooser" in script


class TestCameraLifecycle:
    """Start/stop must be reliable and never swallow a press.

    Reported: repeated presses of Start did nothing, and Stop followed by Start
    left the camera off. The first was a busy flag that discarded presses while
    a slow attempt ran; the second was Android refusing to reopen a camera
    released a moment earlier.
    """

    def test_a_press_while_busy_restarts_rather_than_returning(self, script):
        code = strip_comments(script)
        assert "if (cameraBusy) return" not in code, (
            "presses are silently discarded while an attempt is in flight"
        )
        assert "cameraGeneration" in code, "no way to cancel an in-flight attempt"

    def test_stop_leaves_a_settle_window(self, script):
        assert "cameraSettleUntil" in strip_comments(script)

    def test_stop_cancels_an_attempt_in_flight(self, script):
        stop = re.search(r"function stopCamera\(\) \{.*?\n\}", script, re.S).group(0)
        assert "cameraGeneration" in stop

    def test_starting_shows_progress(self, script):
        """Without feedback, a slow start is indistinguishable from a dead button."""
        assert "setButtonState('starting')" in script

    def test_stop_releases_the_wake_lock(self, script):
        stop = re.search(r"function stopCamera\(\) \{.*?\n\}", script, re.S).group(0)
        assert "releaseWake" in stop


class TestCameraRelease:
    """The camera must be handed back when the page goes away.

    Android reserves a camera for whoever holds the stream. A page reloaded or
    navigated away from while the camera runs leaks that reservation, and the
    next attempt gets NotReadableError while other lenses report NotFoundError
    — curable only by restarting the browser. The scanner this replaced had a
    beforeunload handler; the rewrite dropped it, which is what produced
    "worked once after clearing the cache, never again".
    """

    def test_released_on_pagehide(self, script):
        assert "addEventListener('pagehide'" in script

    def test_released_on_beforeunload(self, script):
        assert "addEventListener('beforeunload'" in script

    def test_released_when_backgrounded(self, script):
        """Holding a camera in a background tab blocks every other app."""
        code = strip_comments(script)
        handler = re.search(r"visibilitychange.*?\n\}\);", code, re.S).group(0)
        assert "releaseCamera" in handler

    def test_resumes_when_brought_back(self, script):
        assert "resumeOnReturn" in script

    def test_not_holding_one_camera_while_asking_for_another(self, script):
        """Requesting a camera while still holding one self-inflicts
        NotReadableError."""
        code = strip_comments(script)
        acquire = code[code.index("async function acquire("):]
        assert "releaseCamera()" in acquire[:2000]

    def test_busy_camera_gets_its_own_advice(self, script):
        """NotReadableError means found-but-held, which needs different
        instructions from 'no camera found'."""
        assert "NotReadableError" in script
        assert "recent apps" in script, "no guidance for a camera held by a dead tab"


class TestMobileVideoElement:
    def test_playsinline_is_set(self, source):
        """Without it iOS takes the video fullscreen instead of inline."""
        video = re.search(r"<video[^>]*>", source).group(0)
        assert "playsinline" in video

    def test_muted_and_autoplay(self, source):
        video = re.search(r"<video[^>]*>", source).group(0)
        assert "muted" in video and "autoplay" in video


class TestFallbacksAlwaysAvailable:
    def test_manual_entry_button_exists(self, source):
        assert 'id="btn-manual"' in source

    def test_camera_picker_exists(self, source):
        assert 'id="start-picker"' in source

    def test_diagnostics_panel_exists(self, source):
        assert 'id="start-diag"' in source


class TestQrLibraryIsLocal:
    def test_jsqr_is_vendored_not_cdn(self, source):
        """Venue wifi is often captive; a CDN fetch would leave no scanner."""
        assert "vendor/jsqr.js" in source
        assert "cdn.jsdelivr" not in source and "unpkg" not in source
