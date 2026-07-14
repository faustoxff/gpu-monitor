import glob
import os
import re
import subprocess
from typing import Dict, Optional

from .base import GPUBackend, GPUStats


def _lspci_intel_names() -> Dict[str, str]:
    """Return {pci_device_id_lower: human_name} for Intel GPUs (vendor 8086)."""
    names: Dict[str, str] = {}
    try:
        result = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True, text=True, timeout=4,
        )
        for line in result.stdout.splitlines():
            m = re.search(r"\[8086:([0-9a-fA-F]{4})\]", line)
            if not m:
                continue
            if not re.search(r"(VGA|Display|3D|GPU)", line, re.I):
                continue
            dev_id = m.group(1).lower()
            desc_m = re.search(r"\]: (.+?) \[8086:", line)
            if desc_m:
                raw = desc_m.group(1)
                raw = re.sub(r"^Intel Corporation\s*", "", raw)
                names[dev_id] = raw.strip()
    except Exception:
        pass
    return names


_INTEL_LSPCI_CACHE: Optional[Dict[str, str]] = None


def _lookup_intel_lspci(device_id_hex: str) -> Optional[str]:
    global _INTEL_LSPCI_CACHE
    if _INTEL_LSPCI_CACHE is None:
        _INTEL_LSPCI_CACHE = _lspci_intel_names()
    return _INTEL_LSPCI_CACHE.get(device_id_hex.lstrip("0x").lower())


class IntelBackend(GPUBackend):
    """Reads Intel GPU metrics from the i915 / xe sysfs interface.

    Intel's kernel drivers expose significantly fewer metrics than AMD or
    NVIDIA.  Typically only GPU frequency and (on some platforms) power
    readings are available.  Temperature and VRAM are rarely exposed and
    will be None on most systems.

    Paths probed:
      Frequency : /sys/class/drm/cardN/gt/gt0/rps_cur_freq_mhz
                  /sys/class/drm/cardN/device/hwmon/hwmonM/freq1_input
      Power     : /sys/class/drm/cardN/device/hwmon/hwmonM/power1_average
      Temperature: /sys/class/drm/cardN/device/hwmon/hwmonM/temp1_input
                   (rare — present on some Tiger Lake / Xe platforms)
    """

    def __init__(self, device_path: str, card_name: str, driver: str) -> None:
        """
        Args:
            device_path: /sys/class/drm/cardN/device
            card_name:   'cardN'
            driver:      'i915' or 'xe'
        """
        self.device_path = device_path
        self.card_name = card_name
        self.driver = driver
        self._hwmon_path: Optional[str] = self._find_hwmon()
        self._gt_path: Optional[str] = self._find_gt()
        self._name: str = self._detect_name()

    # ------------------------------------------------------------------
    # GPUBackend interface
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return self._name

    def get_vendor(self) -> str:
        return "Intel"

    def get_stats(self) -> GPUStats:
        stats: GPUStats = {
            "name": self._name,
            "temp_c": None,
            "usage_pct": None,    # not exposed by i915/xe
            "vram_used_mb": None, # not exposed
            "vram_total_mb": None,
            "clock_mhz": None,
            "power_w": None,
        }

        if self._hwmon_path:
            self._read_hwmon(stats)

        if stats["clock_mhz"] is None and self._gt_path:
            raw = self._read(f"{self._gt_path}/rps_cur_freq_mhz")
            if raw is not None:
                stats["clock_mhz"] = self._to_float(raw)

        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_hwmon(self, stats: GPUStats) -> None:
        hwmon = self._hwmon_path

        # Temperature (millidegrees → °C) — rare but possible
        raw = self._read(f"{hwmon}/temp1_input")
        if raw is not None:
            v = self._to_float(raw)
            stats["temp_c"] = v / 1000.0 if v is not None else None

        # Power (microwatts → W)
        for fname in ("power1_average", "power1_input"):
            raw = self._read(f"{hwmon}/{fname}")
            if raw is not None:
                v = self._to_float(raw)
                if v is not None:
                    stats["power_w"] = v / 1_000_000.0
                    break

        # Frequency (Hz → MHz) — present on some Xe platforms via hwmon
        raw = self._read(f"{hwmon}/freq1_input")
        if raw is not None:
            v = self._to_float(raw)
            stats["clock_mhz"] = v / 1_000_000.0 if v is not None else None

    def _find_hwmon(self) -> Optional[str]:
        matches = glob.glob(f"{self.device_path}/hwmon/hwmon*")
        return matches[0] if matches else None

    def _find_gt(self) -> Optional[str]:
        # i915: /sys/class/drm/cardN/gt/gt0
        gt = f"/sys/class/drm/{self.card_name}/gt/gt0"
        if os.path.isdir(gt):
            return gt
        # xe: sometimes under device/
        gt2 = f"{self.device_path}/gt/gt0"
        if os.path.isdir(gt2):
            return gt2
        return None

    def _detect_name(self) -> str:
        device_id = self._read(f"{self.device_path}/device") or "0x????"
        human = _lookup_intel_lspci(device_id)
        if human:
            return f"{human} ({self.driver})"
        return f"Intel GPU [{device_id}] ({self.driver})"

    @staticmethod
    def _read(path: str) -> Optional[str]:
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            return None

    @staticmethod
    def _to_float(s: str) -> Optional[float]:
        try:
            return float(s)
        except ValueError:
            return None
