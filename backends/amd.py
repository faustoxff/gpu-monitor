import glob
import os
import re
import subprocess
from typing import Dict, Optional

from .base import GPUBackend, GPUStats


def _lspci_names() -> Dict[str, str]:
    """Return {pci_device_id_lower: human_name} from lspci for AMD (vendor 1002)."""
    names: Dict[str, str] = {}
    try:
        result = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True, text=True, timeout=4,
        )
        for line in result.stdout.splitlines():
            # Example: "03:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Navi 33 [...] [1002:7480] (rev cf)"
            m = re.search(r"\[1002:([0-9a-fA-F]{4})\]", line)
            if not m:
                continue
            dev_id = m.group(1).lower()
            # Extract the model name between the vendor description and the [1002:…] tag.
            # Everything after the "]:" block and before the final "[1002:…]"
            desc_m = re.search(r"\]: (.+?) \[1002:", line)
            if desc_m:
                # Strip redundant "AMD/ATI" prefix
                raw = desc_m.group(1)
                raw = re.sub(r"^Advanced Micro Devices,? Inc\. \[AMD/ATI\]\s*", "", raw)
                names[dev_id] = raw.strip()
    except Exception:
        pass
    return names


_LSPCI_CACHE: Optional[Dict[str, str]] = None


def _lookup_lspci(device_id_hex: str) -> Optional[str]:
    global _LSPCI_CACHE
    if _LSPCI_CACHE is None:
        _LSPCI_CACHE = _lspci_names()
    return _LSPCI_CACHE.get(device_id_hex.lstrip("0x").lower())


class AMDBackend(GPUBackend):
    """Reads AMD GPU metrics from the amdgpu sysfs interface.

    Works for both discrete GPUs and APUs (integrated AMD graphics).
    All paths are under /sys/class/drm/cardN/device/.
    """

    def __init__(self, device_path: str, card_name: str) -> None:
        """
        Args:
            device_path: Absolute path to /sys/class/drm/cardN/device
            card_name:   DRM card identifier, e.g. 'card0'
        """
        self.device_path = device_path
        self.card_name = card_name
        self._hwmon_path: Optional[str] = self._find_hwmon()
        self._name: str = self._detect_name()

    # ------------------------------------------------------------------
    # GPUBackend interface
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return self._name

    def get_vendor(self) -> str:
        return "AMD"

    def get_stats(self) -> GPUStats:
        stats: GPUStats = {
            "name": self._name,
            "temp_c": None,
            "usage_pct": None,
            "vram_used_mb": None,
            "vram_total_mb": None,
            "clock_mhz": None,
            "power_w": None,
        }

        # GPU utilisation
        val = self._read(f"{self.device_path}/gpu_busy_percent")
        if val is not None:
            stats["usage_pct"] = self._to_float(val)

        # VRAM (bytes → MiB)
        for key, fname in (
            ("vram_used_mb", "mem_info_vram_used"),
            ("vram_total_mb", "mem_info_vram_total"),
        ):
            raw = self._read(f"{self.device_path}/{fname}")
            if raw is not None:
                v = self._to_float(raw)
                stats[key] = v / (1024 * 1024) if v is not None else None

        if self._hwmon_path:
            self._read_hwmon(stats)

        # Fallback clock from pp_dpm_sclk when hwmon freq1_input is absent
        if stats["clock_mhz"] is None:
            stats["clock_mhz"] = self._read_pp_dpm_sclk()

        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_hwmon(self, stats: GPUStats) -> None:
        hwmon = self._hwmon_path

        # Temperature — millidegrees → °C
        raw = self._read(f"{hwmon}/temp1_input")
        if raw is not None:
            v = self._to_float(raw)
            stats["temp_c"] = v / 1000.0 if v is not None else None

        # Power — prefer average, fall back to instantaneous (microwatts → W)
        for fname in ("power1_average", "power1_input"):
            raw = self._read(f"{hwmon}/{fname}")
            if raw is not None:
                v = self._to_float(raw)
                if v is not None:
                    stats["power_w"] = v / 1_000_000.0
                    break

        # Core clock — Hz → MHz
        raw = self._read(f"{hwmon}/freq1_input")
        if raw is not None:
            v = self._to_float(raw)
            stats["clock_mhz"] = v / 1_000_000.0 if v is not None else None

    def _read_pp_dpm_sclk(self) -> Optional[float]:
        """Parse the currently active clock from pp_dpm_sclk.

        Example content:
            0: 400Mhz
            1: 600Mhz *
            2: 2200Mhz
        The active level is marked with '*'.
        """
        raw = self._read(f"{self.device_path}/pp_dpm_sclk")
        if raw is None:
            return None
        for line in raw.splitlines():
            if "*" in line:
                try:
                    # "1: 600Mhz *" → 600.0
                    return float(line.split(":")[1].strip().split("Mhz")[0].strip())
                except (IndexError, ValueError):
                    pass
        return None

    def _find_hwmon(self) -> Optional[str]:
        matches = glob.glob(f"{self.device_path}/hwmon/hwmon*")
        return matches[0] if matches else None

    def _detect_name(self) -> str:
        device_id = self._read(f"{self.device_path}/device") or "0x????"
        # Distinguish integrated (APU) from discrete by VRAM total.
        # APUs share system RAM so vram_total tends to be small (≤512 MiB).
        vram_raw = self._read(f"{self.device_path}/mem_info_vram_total")
        kind = ""
        if vram_raw is not None:
            try:
                vram_mb = int(vram_raw) / (1024 * 1024)
                kind = " (APU)" if vram_mb <= 512 else ""
            except ValueError:
                pass
        # Prefer the human-readable name from lspci.
        human = _lookup_lspci(device_id)
        if human:
            return f"{human}{kind}"
        return f"AMD GPU [{device_id}]{kind}"

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
