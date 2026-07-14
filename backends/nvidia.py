import subprocess
from typing import Optional

from .base import GPUBackend, GPUStats

# pynvml is an optional dependency.  We import lazily and fall back to
# shelling out to nvidia-smi if the library is absent.
try:
    import pynvml as _pynvml  # type: ignore

    _pynvml.nvmlInit()
    _NVML_AVAILABLE = True
except Exception:
    _pynvml = None  # type: ignore
    _NVML_AVAILABLE = False


class NVIDIABackend(GPUBackend):
    """Reads NVIDIA GPU metrics via pynvml when available, nvidia-smi otherwise.

    pynvml path: direct in-process calls, very fast.
    nvidia-smi path: subprocess with --format=csv, ~50-100 ms overhead per poll.
    """

    def __init__(self, gpu_index: int) -> None:
        self.gpu_index = gpu_index
        self._handle = None
        self._use_nvml = False
        self._name = f"NVIDIA GPU #{gpu_index}"

        if _NVML_AVAILABLE and _pynvml is not None:
            try:
                self._handle = _pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
                raw_name = _pynvml.nvmlDeviceGetName(self._handle)
                self._name = raw_name.decode() if isinstance(raw_name, bytes) else raw_name
                self._use_nvml = True
            except Exception:
                pass

        if not self._use_nvml:
            self._name = self._smi_name()

    # ------------------------------------------------------------------
    # GPUBackend interface
    # ------------------------------------------------------------------

    def get_name(self) -> str:
        return self._name

    def get_vendor(self) -> str:
        return "NVIDIA"

    def get_stats(self) -> GPUStats:
        if self._use_nvml and self._handle is not None:
            return self._stats_nvml()
        return self._stats_smi()

    # ------------------------------------------------------------------
    # pynvml path
    # ------------------------------------------------------------------

    def _stats_nvml(self) -> GPUStats:
        pynvml = _pynvml
        h = self._handle
        stats: GPUStats = {
            "name": self._name,
            "temp_c": None,
            "usage_pct": None,
            "vram_used_mb": None,
            "vram_total_mb": None,
            "clock_mhz": None,
            "power_w": None,
        }

        try:
            stats["temp_c"] = float(
                pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            )
        except Exception:
            pass

        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            stats["usage_pct"] = float(util.gpu)
        except Exception:
            pass

        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            stats["vram_used_mb"] = mem.used / (1024 * 1024)
            stats["vram_total_mb"] = mem.total / (1024 * 1024)
        except Exception:
            pass

        try:
            stats["clock_mhz"] = float(
                pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS)
            )
        except Exception:
            pass

        try:
            # nvml returns milliwatts
            stats["power_w"] = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
        except Exception:
            pass

        return stats

    # ------------------------------------------------------------------
    # nvidia-smi fallback
    # ------------------------------------------------------------------

    _SMI_QUERY = (
        "temperature.gpu,"
        "utilization.gpu,"
        "memory.used,"
        "memory.total,"
        "clocks.current.graphics,"
        "power.draw"
    )

    def _stats_smi(self) -> GPUStats:
        stats: GPUStats = {
            "name": self._name,
            "temp_c": None,
            "usage_pct": None,
            "vram_used_mb": None,
            "vram_total_mb": None,
            "clock_mhz": None,
            "power_w": None,
        }
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={self._SMI_QUERY}",
                    "--format=csv,noheader,nounits",
                    f"--id={self.gpu_index}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return stats
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) < 6:
                return stats
            keys = ("temp_c", "usage_pct", "vram_used_mb", "vram_total_mb", "clock_mhz", "power_w")
            for key, raw in zip(keys, parts):
                try:
                    stats[key] = float(raw)  # type: ignore[literal-required]
                except ValueError:
                    pass
        except Exception:
            pass
        return stats

    def _smi_name(self) -> str:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name",
                    "--format=csv,noheader,nounits",
                    f"--id={self.gpu_index}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return f"NVIDIA GPU #{self.gpu_index}"
