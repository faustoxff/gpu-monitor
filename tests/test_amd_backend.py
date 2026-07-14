"""Unit tests for AMDBackend.

All sysfs reads are mocked via unittest.mock so no real hardware is needed.
The key invariant under test: any field the driver doesn't expose must be
None in the returned dict — never 0, never a fabricated value.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backends.amd import AMDBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backend(sysfs: dict, hwmon: dict | None = None) -> AMDBackend:
    """Build an AMDBackend with mocked sysfs reads.

    Args:
        sysfs: {relative_path: content} rooted at /fake/device/
        hwmon: {relative_path: content} rooted at /fake/device/hwmon/hwmon0/
               Pass None to simulate absent hwmon directory.
    """
    device_path = "/fake/device"
    hwmon_path = "/fake/device/hwmon/hwmon0"

    def fake_read(path: str):
        # Check the longer (more specific) hwmon prefix first — the hwmon path
        # is a subdirectory of device_path, so order matters.
        if hwmon is not None and path.startswith(hwmon_path + "/"):
            key = path[len(hwmon_path) + 1:]
            return hwmon.get(key)
        if path.startswith(device_path + "/"):
            key = path[len(device_path) + 1:]
            return sysfs.get(key)
        return None

    with (
        patch("backends.amd._lookup_lspci", return_value=None),
        patch.object(AMDBackend, "_read", side_effect=fake_read),
        patch("glob.glob", side_effect=lambda p: [hwmon_path] if (hwmon is not None and "hwmon" in p) else []),
    ):
        backend = AMDBackend(device_path, "card0")
        # Reattach the mocked _read so get_stats() calls also use it.
        backend._read = fake_read          # type: ignore[method-assign]
        backend._hwmon_path = hwmon_path if hwmon is not None else None
    return backend


# ---------------------------------------------------------------------------
# Name detection
# ---------------------------------------------------------------------------

class TestAMDName(unittest.TestCase):
    def test_name_from_lspci(self):
        with (
            patch("backends.amd._lookup_lspci", return_value="Navi 33 [Radeon RX 7600]"),
            patch.object(AMDBackend, "_read", side_effect=lambda p: None),
            patch("glob.glob", return_value=[]),
        ):
            b = AMDBackend("/fake/device", "card0")
        self.assertIn("Navi 33", b.get_name())

    def test_name_fallback_to_pci_id(self):
        sysfs = {"device": "0x7480", "vendor": "0x1002"}
        b = _make_backend(sysfs, hwmon=None)
        self.assertIn("0x7480", b.get_name())

    def test_apu_suffix_when_vram_small(self):
        sysfs = {"device": "0x164e", "vendor": "0x1002",
                 "mem_info_vram_total": str(512 * 1024 * 1024)}
        b = _make_backend(sysfs, hwmon=None)
        self.assertIn("APU", b.get_name())

    def test_no_apu_suffix_for_dgpu(self):
        sysfs = {"device": "0x7480", "vendor": "0x1002",
                 "mem_info_vram_total": str(8192 * 1024 * 1024)}
        b = _make_backend(sysfs, hwmon=None)
        self.assertNotIn("APU", b.get_name())

    def test_get_vendor_always_amd(self):
        b = _make_backend({}, hwmon=None)
        self.assertEqual(b.get_vendor(), "AMD")


# ---------------------------------------------------------------------------
# Stats — happy path (all metrics present)
# ---------------------------------------------------------------------------

class TestAMDStatsFullData(unittest.TestCase):
    def setUp(self):
        self.sysfs = {
            "gpu_busy_percent":  "42",
            "mem_info_vram_used": str(1024 * 1024 * 1024),   # 1 GiB
            "mem_info_vram_total": str(8 * 1024 * 1024 * 1024),
        }
        self.hwmon = {
            "temp1_input":   "65000",     # 65 °C in millidegrees
            "power1_average": "95000000", # 95 W in microwatts
            "freq1_input":   "1800000000", # 1800 MHz in Hz
        }
        self.backend = _make_backend(self.sysfs, self.hwmon)

    def test_usage_pct(self):
        self.assertAlmostEqual(self.backend.get_stats()["usage_pct"], 42.0)

    def test_temperature(self):
        self.assertAlmostEqual(self.backend.get_stats()["temp_c"], 65.0)

    def test_vram_used_mib(self):
        self.assertAlmostEqual(self.backend.get_stats()["vram_used_mb"], 1024.0)

    def test_vram_total_mib(self):
        self.assertAlmostEqual(self.backend.get_stats()["vram_total_mb"], 8192.0)

    def test_clock_mhz(self):
        self.assertAlmostEqual(self.backend.get_stats()["clock_mhz"], 1800.0)

    def test_power_w(self):
        self.assertAlmostEqual(self.backend.get_stats()["power_w"], 95.0)

    def test_name_in_stats(self):
        self.assertIsInstance(self.backend.get_stats()["name"], str)
        self.assertTrue(len(self.backend.get_stats()["name"]) > 0)


# ---------------------------------------------------------------------------
# Stats — missing files yield None, not 0
# ---------------------------------------------------------------------------

class TestAMDStatsNoneOnMissing(unittest.TestCase):
    """The critical invariant: absent sysfs node → None in the returned dict."""

    def test_missing_temp_is_none(self):
        b = _make_backend({}, hwmon={})   # hwmon present but empty
        self.assertIsNone(b.get_stats()["temp_c"])

    def test_missing_power_is_none(self):
        b = _make_backend({}, hwmon={})
        self.assertIsNone(b.get_stats()["power_w"])

    def test_missing_usage_is_none(self):
        b = _make_backend({}, hwmon=None)
        self.assertIsNone(b.get_stats()["usage_pct"])

    def test_missing_vram_used_is_none(self):
        b = _make_backend({}, hwmon=None)
        self.assertIsNone(b.get_stats()["vram_used_mb"])

    def test_missing_vram_total_is_none(self):
        b = _make_backend({}, hwmon=None)
        self.assertIsNone(b.get_stats()["vram_total_mb"])

    def test_missing_clock_is_none(self):
        b = _make_backend({}, hwmon=None)   # no freq1_input, no pp_dpm_sclk
        self.assertIsNone(b.get_stats()["clock_mhz"])

    def test_no_hwmon_leaves_temp_none(self):
        b = _make_backend({"gpu_busy_percent": "10"}, hwmon=None)
        stats = b.get_stats()
        self.assertIsNone(stats["temp_c"])
        self.assertIsNone(stats["power_w"])
        self.assertAlmostEqual(stats["usage_pct"], 10.0)  # unaffected


# ---------------------------------------------------------------------------
# pp_dpm_sclk clock fallback
# ---------------------------------------------------------------------------

class TestAMDPpDpmSclk(unittest.TestCase):
    def _backend_with_sclk(self, content: str) -> AMDBackend:
        sysfs = {"pp_dpm_sclk": content}
        return _make_backend(sysfs, hwmon={})   # hwmon present but no freq1_input

    def test_active_clock_parsed(self):
        content = "0: 300Mhz \n1: 600Mhz *\n2: 2200Mhz \n"
        b = self._backend_with_sclk(content)
        self.assertAlmostEqual(b.get_stats()["clock_mhz"], 600.0)

    def test_active_clock_first_entry(self):
        content = "0: 400Mhz *\n1: 800Mhz \n"
        b = self._backend_with_sclk(content)
        self.assertAlmostEqual(b.get_stats()["clock_mhz"], 400.0)

    def test_active_clock_last_entry(self):
        content = "0: 500Mhz \n1: 1000Mhz \n2: 2283Mhz *\n"
        b = self._backend_with_sclk(content)
        self.assertAlmostEqual(b.get_stats()["clock_mhz"], 2283.0)

    def test_no_asterisk_returns_none(self):
        content = "0: 300Mhz \n1: 600Mhz \n"
        b = self._backend_with_sclk(content)
        self.assertIsNone(b.get_stats()["clock_mhz"])

    def test_hwmon_freq_takes_priority_over_pp_dpm(self):
        """freq1_input must win when both sources are available."""
        sysfs = {"pp_dpm_sclk": "0: 999Mhz *\n"}
        hwmon = {"freq1_input": "1500000000"}   # 1500 MHz
        b = _make_backend(sysfs, hwmon)
        self.assertAlmostEqual(b.get_stats()["clock_mhz"], 1500.0)


# ---------------------------------------------------------------------------
# Power fallback: power1_average → power1_input
# ---------------------------------------------------------------------------

class TestAMDPowerFallback(unittest.TestCase):
    def test_power1_average_preferred(self):
        hwmon = {"power1_average": "80000000", "power1_input": "90000000"}
        b = _make_backend({}, hwmon)
        self.assertAlmostEqual(b.get_stats()["power_w"], 80.0)

    def test_power1_input_fallback(self):
        hwmon = {"power1_input": "50000000"}
        b = _make_backend({}, hwmon)
        self.assertAlmostEqual(b.get_stats()["power_w"], 50.0)


# ---------------------------------------------------------------------------
# Corrupt / non-numeric values
# ---------------------------------------------------------------------------

class TestAMDCorruptData(unittest.TestCase):
    def test_non_numeric_usage_is_none(self):
        b = _make_backend({"gpu_busy_percent": "N/A"}, hwmon=None)
        self.assertIsNone(b.get_stats()["usage_pct"])

    def test_non_numeric_temp_is_none(self):
        b = _make_backend({}, hwmon={"temp1_input": "unavailable"})
        self.assertIsNone(b.get_stats()["temp_c"])

    def test_non_numeric_vram_is_none(self):
        b = _make_backend({"mem_info_vram_total": "error"}, hwmon=None)
        self.assertIsNone(b.get_stats()["vram_total_mb"])


if __name__ == "__main__":
    unittest.main()
