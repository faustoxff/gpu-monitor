from abc import ABC, abstractmethod
from typing import Optional
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # type: ignore


class GPUStats(TypedDict):
    name: str
    temp_c: Optional[float]
    usage_pct: Optional[float]
    vram_used_mb: Optional[float]
    vram_total_mb: Optional[float]
    clock_mhz: Optional[float]
    power_w: Optional[float]


class GPUBackend(ABC):
    """Common interface all GPU backends must implement."""

    @abstractmethod
    def get_stats(self) -> GPUStats:
        """Return a normalised snapshot of the GPU's current state.

        Any metric the hardware or driver does not expose must be None —
        never 0 or a fabricated value.
        """

    @abstractmethod
    def get_name(self) -> str:
        """Human-readable GPU model name."""

    @abstractmethod
    def get_vendor(self) -> str:
        """Short vendor tag: 'AMD', 'NVIDIA', or 'Intel'."""
