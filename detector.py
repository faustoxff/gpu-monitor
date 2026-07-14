"""GPU auto-detection.

Iterates /sys/class/drm/cardN entries, reads the driver symlink, and
instantiates the matching backend.  NVIDIA GPUs are detected first via
pynvml / nvidia-smi because their sysfs presence depends on the driver
version and the nvidia_drm kernel module.
"""

import glob
import os
import subprocess
from typing import List

from backends.base import GPUBackend
from backends.amd import AMDBackend
from backends.intel import IntelBackend
from backends.nvidia import NVIDIABackend


def detect_gpus() -> List[GPUBackend]:
    """Return one backend per detected GPU, ordered by DRM card index."""
    backends: List[GPUBackend] = []
    nvidia_added = False

    for card_dir in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        card_name = os.path.basename(card_dir)
        # Skip connector nodes like card0-DP-1
        if "-" in card_name:
            continue
        if not os.path.isdir(card_dir):
            continue

        device_path = os.path.join(card_dir, "device")
        driver_link = os.path.join(device_path, "driver")

        if not os.path.islink(driver_link):
            continue

        driver = os.path.basename(os.readlink(driver_link))

        if driver == "amdgpu":
            backends.append(AMDBackend(device_path, card_name))

        elif driver in ("i915", "xe"):
            backends.append(IntelBackend(device_path, card_name, driver))

        elif driver in ("nvidia", "nouveau") and not nvidia_added:
            # Add all NVIDIA GPUs at once via pynvml / nvidia-smi count.
            nvidia_added = True
            for idx in _count_nvidia_gpus():
                backends.append(NVIDIABackend(idx))

    # If NVIDIA GPUs exist but have no DRM node (possible without nvidia_drm)
    if not nvidia_added:
        indices = _count_nvidia_gpus()
        for idx in indices:
            backends.append(NVIDIABackend(idx))

    return backends


def _count_nvidia_gpus() -> List[int]:
    """Return a list of NVIDIA GPU indices [0, 1, …, N-1]."""
    # pynvml path
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        return list(range(pynvml.nvmlDeviceGetCount()))
    except Exception:
        pass

    # nvidia-smi fallback
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            return list(range(len(lines)))
    except Exception:
        pass

    return []
