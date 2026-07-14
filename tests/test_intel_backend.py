"""Unit tests for IntelBackend.

Intel exposes far fewer sysfs paths than AMD.  The main things to verify:
  - Usage % and VRAM are always None (driver limitation, not a bug)
  - Clock is read from gt/gt0/rps_cur_freq_mhz when available
  - Power and temperature come from hwmon when present
  - Any absent path → None, not 0
"""

import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backends.intel import IntelBackend


def _make_backend(
    hwmon: dict | None,
    gt_freq_mhz: str | None = None,
    driver: str = "i915",
) -> IntelBackend:
    device_path = "/fake/device"
    hwmon_path = "/fake/device/hwmon/hwmon0"
    gt_path = "/sys/class/drm/card0/gt/gt0"

    def fake_read(path: str):
        if path.startswith(hwmon_path + "/") and hwmon is not None:
            return hwmon.get(path[len(hwmon_path) + 1:])
        if path == f"{gt_path}/rps_cur_freq_mhz":
            return gt_freq_mhz
        if path.endswith("/device"):
            return "0x9a49"
        return None

    with (
        patch("backends.intel._lookup_intel_lspci", return_value=None),
        patch.object(IntelBackend, "_read", side_effect=fake_read),
        patch("glob.glob", side_effect=lambda p: [hwmon_path] if (hwmon is not None and "hwmon" in p) else []),
        patch("os.path.isdir", side_effect=lambda p: p == gt_path),
    ):
        b = IntelBackend(device_path, "card0", driver)
        b._read = fake_read               # type: ignore[method-assign]
        b._hwmon_path = hwmon_path if hwmon is not None else None
        b._gt_path = gt_path if gt_freq_mhz is not None else None
    return b


class TestIntelVendor(unittest.TestCase):
    def test_vendor_is_intel(self):
        self.assertEqual(_make_backend(None).get_vendor(), "Intel")


class TestIntelDriverMetadata(unittest.TestCase):
    def test_driver_in_name_i915(self):
        self.assertIn("i915", _make_backend(None, driver="i915").get_name())

    def test_driver_in_name_xe(self):
        self.assertIn("xe", _make_backend(None, driver="xe").get_name())

    def test_name_from_lspci(self):
        with patch("backends.intel._lookup_intel_lspci", return_value="Iris Xe Graphics"):
            with (
                patch.object(IntelBackend, "_read", return_value=None),
                patch("glob.glob", return_value=[]),
                patch("os.path.isdir", return_value=False),
            ):
                b = IntelBackend("/fake/device", "card0", "i915")
        self.assertIn("Iris Xe", b.get_name())


class TestIntelDriverDoesNotExposeUsageOrVRAM(unittest.TestCase):
    """These must always be None — the driver simply doesn't expose them."""

    def test_usage_pct_always_none(self):
        self.assertIsNone(_make_backend(None).get_stats()["usage_pct"])

    def test_vram_used_always_none(self):
        self.assertIsNone(_make_backend(None).get_stats()["vram_used_mb"])

    def test_vram_total_always_none(self):
        self.assertIsNone(_make_backend(None).get_stats()["vram_total_mb"])


class TestIntelClock(unittest.TestCase):
    def test_clock_from_gt_path(self):
        b = _make_backend(hwmon=None, gt_freq_mhz="1300")
        self.assertAlmostEqual(b.get_stats()["clock_mhz"], 1300.0)

    def test_clock_none_when_gt_absent(self):
        b = _make_backend(hwmon=None, gt_freq_mhz=None)
        self.assertIsNone(b.get_stats()["clock_mhz"])

    def test_hwmon_freq_used_when_gt_absent(self):
        hwmon = {"freq1_input": "1200000000"}   # 1200 MHz in Hz
        b = _make_backend(hwmon=hwmon, gt_freq_mhz=None)
        self.assertAlmostEqual(b.get_stats()["clock_mhz"], 1200.0)


class TestIntelPower(unittest.TestCase):
    def test_power_from_power1_average(self):
        hwmon = {"power1_average": "15000000"}  # 15 W
        b = _make_backend(hwmon=hwmon)
        self.assertAlmostEqual(b.get_stats()["power_w"], 15.0)

    def test_power_fallback_to_power1_input(self):
        hwmon = {"power1_input": "20000000"}  # 20 W
        b = _make_backend(hwmon=hwmon)
        self.assertAlmostEqual(b.get_stats()["power_w"], 20.0)

    def test_power_none_when_hwmon_absent(self):
        self.assertIsNone(_make_backend(hwmon=None).get_stats()["power_w"])


class TestIntelTemperature(unittest.TestCase):
    def test_temp_from_hwmon(self):
        hwmon = {"temp1_input": "55000"}  # 55 °C in millidegrees
        b = _make_backend(hwmon=hwmon)
        self.assertAlmostEqual(b.get_stats()["temp_c"], 55.0)

    def test_temp_none_when_absent(self):
        self.assertIsNone(_make_backend(hwmon={}).get_stats()["temp_c"])

    def test_temp_none_when_no_hwmon(self):
        self.assertIsNone(_make_backend(hwmon=None).get_stats()["temp_c"])


class TestIntelNoneNotZero(unittest.TestCase):
    """Absent sysfs nodes must produce None, never 0."""

    def test_all_missing_fields_are_none_not_zero(self):
        b = _make_backend(hwmon=None, gt_freq_mhz=None)
        stats = b.get_stats()
        for field in ("temp_c", "usage_pct", "vram_used_mb", "vram_total_mb",
                      "clock_mhz", "power_w"):
            self.assertIsNone(stats[field], msg=f"{field} should be None, got {stats[field]}")


if __name__ == "__main__":
    unittest.main()
