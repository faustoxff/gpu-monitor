"""Tests that GPUPanel survives a failing backend without crashing the app.

Uses a minimal QApplication so Qt widgets can be instantiated, but no window
is shown — the test runs headless.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)


from backends.base import GPUBackend, GPUStats
from ui.gpu_panel import GPUPanel


class _GoodBackend(GPUBackend):
    def get_vendor(self): return "AMD"
    def get_name(self): return "Test GPU"
    def get_stats(self) -> GPUStats:
        return {
            "name": "Test GPU",
            "temp_c": 55.0,
            "usage_pct": 40.0,
            "vram_used_mb": 1024.0,
            "vram_total_mb": 8192.0,
            "clock_mhz": 1800.0,
            "power_w": 90.0,
        }


class _PermissionErrorBackend(GPUBackend):
    """Simulates a backend whose sysfs path is unreadable."""
    def get_vendor(self): return "AMD"
    def get_name(self): return "Permission Error GPU"
    def get_stats(self) -> GPUStats:
        raise PermissionError("/sys/class/drm/card0/device/gpu_busy_percent: Permission denied")


class _IntermittentBackend(GPUBackend):
    """Raises on every other call — simulates transient I/O errors."""
    def __init__(self):
        self._call = 0
    def get_vendor(self): return "AMD"
    def get_name(self): return "Intermittent GPU"
    def get_stats(self) -> GPUStats:
        self._call += 1
        if self._call % 2 == 0:
            raise OSError("sysfs temporarily unavailable")
        return {
            "name": "Intermittent GPU",
            "temp_c": 60.0, "usage_pct": 50.0,
            "vram_used_mb": None, "vram_total_mb": None,
            "clock_mhz": None, "power_w": None,
        }


class _NoneEverythingBackend(GPUBackend):
    """Backend where every optional field is None (no driver support)."""
    def get_vendor(self): return "Intel"
    def get_name(self): return "Intel i915 GPU"
    def get_stats(self) -> GPUStats:
        return {
            "name": "Intel i915 GPU",
            "temp_c": None, "usage_pct": None,
            "vram_used_mb": None, "vram_total_mb": None,
            "clock_mhz": 1200.0, "power_w": None,
        }


class TestPanelGoodBackend(unittest.TestCase):
    def setUp(self):
        self.panel = GPUPanel(_GoodBackend())

    def test_refresh_does_not_raise(self):
        self.panel.refresh()   # must not throw

    def test_refresh_twice_does_not_raise(self):
        self.panel.refresh()
        self.panel.refresh()

    def test_error_label_hidden_on_success(self):
        self.panel.refresh()
        # isHidden() reflects this widget's own show/hide state independent of
        # whether the parent panel is currently shown in a window.
        self.assertTrue(self.panel._error_label.isHidden())


class TestPanelPermissionError(unittest.TestCase):
    def setUp(self):
        self.panel = GPUPanel(_PermissionErrorBackend())

    def test_refresh_does_not_crash_app(self):
        """The most important test: an exception in get_stats() must not propagate."""
        try:
            self.panel.refresh()
        except Exception as exc:
            self.fail(f"refresh() raised unexpectedly: {exc}")

    def test_error_label_visible_after_failure(self):
        self.panel.refresh()
        self.assertFalse(self.panel._error_label.isHidden())

    def test_error_message_contains_permission_text(self):
        self.panel.refresh()
        self.assertIn("Permission", self.panel._error_label.text())

    def test_status_label_hidden_on_error(self):
        self.panel.refresh()
        self.assertTrue(self.panel._status_label.isHidden())

    def test_error_dot_color_changes(self):
        self.panel.refresh()
        # Dot style should contain the error red, not the ok green
        style = self.panel._dot.styleSheet()
        self.assertNotIn("#4ade80", style)   # ok green absent
        self.assertIn("#f87171", style)      # error red present


class TestPanelIntermittentErrors(unittest.TestCase):
    def setUp(self):
        self.panel = GPUPanel(_IntermittentBackend())

    def test_alternating_ok_error_ok_does_not_crash(self):
        """Error recovery: panel oscillates between OK and error state cleanly."""
        for _ in range(6):
            try:
                self.panel.refresh()
            except Exception as exc:
                self.fail(f"refresh() raised: {exc}")

    def test_error_label_hides_on_recovery(self):
        # call 1 → OK (no error shown)
        self.panel.refresh()
        self.assertTrue(self.panel._error_label.isHidden())
        # call 2 → error
        self.panel.refresh()
        self.assertFalse(self.panel._error_label.isHidden())
        # call 3 → recovery
        self.panel.refresh()
        self.assertTrue(self.panel._error_label.isHidden())


class TestPanelNoneMetrics(unittest.TestCase):
    """All-None optional fields must not crash — they render as '—'."""

    def setUp(self):
        self.panel = GPUPanel(_NoneEverythingBackend())

    def test_refresh_with_all_nones_does_not_raise(self):
        try:
            self.panel.refresh()
        except Exception as exc:
            self.fail(f"refresh() raised: {exc}")

    def test_partial_none_handled(self):
        """Only clock is present; all others are None."""
        self.panel.refresh()
        self.assertFalse(self.panel._error_label.isVisible())


if __name__ == "__main__":
    unittest.main()
