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

    def test_falls_back_to_the_front_camera(self, script):
        assert "facingMode: 'user'" in script

    def test_tries_plain_video_true(self, script):
        assert re.search(r"\{\s*video:\s*true\s*\}", script)

    def test_checks_the_track_is_live(self, script):
        """A stream can return with no track, or one already ended."""
        assert "readyState === 'live'" in script

    def test_releases_streams_it_cannot_use(self, script):
        assert "releaseStream" in script

    def test_permission_refusal_short_circuits(self, script):
        assert "NotAllowedError" in script


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
