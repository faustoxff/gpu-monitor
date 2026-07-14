"""Unit tests for the GPU detector.

Tests the detection logic without touching real sysfs or spawning subprocesses.
What's under test:
  - Driver symlink → correct backend class mapping
  - Connector nodes (card0-DP-1) are skipped
  - Cards are processed in sorted order (card0 before card1)
  - Multiple NVIDIA GPUs are enumerated once, not once per card
  - Cards with unrecognised drivers are silently skipped
  - If no DRM node exists for NVIDIA but nvidia-smi/pynvml finds GPUs, they
    are still added (the fallback path at end of detect_gpus)
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import detector as det
from backends.amd import AMDBackend
from backends.intel import IntelBackend
from backends.nvidia import NVIDIABackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drm_glob(cards: list[str]):
    """Return a glob side_effect that emits /sys/class/drm/<name> paths."""
    return [f"/sys/class/drm/{c}" for c in cards]


def _patch_card(driver_name: str):
    """Minimal patches to make a single DRM card look like it uses driver_name."""
    return {
        "os.path.isdir": True,
        "os.path.islink": True,
        "os.readlink": f"../../../../bus/pci/drivers/{driver_name}",
    }


# ---------------------------------------------------------------------------
# Connector / non-card filtering
# ---------------------------------------------------------------------------

class TestConnectorFiltering(unittest.TestCase):
    @patch("detector.AMDBackend", autospec=True)
    @patch("detector.glob.glob", return_value=_drm_glob(["card0-DP-1", "card0-HDMI-A-1"]))
    @patch("detector.os.path.isdir", return_value=True)
    @patch("detector._count_nvidia_gpus", return_value=[])
    def test_connector_nodes_skipped(self, _nv, _isdir, _glob, MockAMD):
        backends = det.detect_gpus()
        MockAMD.assert_not_called()
        self.assertEqual(backends, [])

    @patch("detector.AMDBackend", autospec=True)
    @patch("detector.glob.glob", return_value=_drm_glob(["card0", "card0-DP-1", "card1"]))
    @patch("detector.os.path.isdir", return_value=True)
    @patch("detector.os.path.islink", return_value=True)
    @patch("detector.os.readlink", return_value="../../../../bus/pci/drivers/amdgpu")
    @patch("detector._count_nvidia_gpus", return_value=[])
    def test_only_plain_cards_processed(self, _nv, _readlink, _islink, _isdir, _glob, MockAMD):
        det.detect_gpus()
        # Called exactly twice: card0 and card1, not the connector
        self.assertEqual(MockAMD.call_count, 2)


# ---------------------------------------------------------------------------
# Driver → backend mapping
# ---------------------------------------------------------------------------

class TestDriverMapping(unittest.TestCase):
    def _run_with_driver(self, driver: str):
        with (
            patch("detector.glob.glob", return_value=_drm_glob(["card0"])),
            patch("detector.os.path.isdir", return_value=True),
            patch("detector.os.path.islink", return_value=True),
            patch("detector.os.readlink", return_value=f"../../../../bus/pci/drivers/{driver}"),
            patch("detector._count_nvidia_gpus", return_value=[]),
            patch("detector.AMDBackend") as MockAMD,
            patch("detector.IntelBackend") as MockIntel,
            patch("detector.NVIDIABackend") as MockNV,
        ):
            backends = det.detect_gpus()
            return backends, MockAMD, MockIntel, MockNV

    def test_amdgpu_creates_amd_backend(self):
        _, MockAMD, MockIntel, MockNV = self._run_with_driver("amdgpu")
        MockAMD.assert_called_once()
        MockIntel.assert_not_called()
        MockNV.assert_not_called()

    def test_i915_creates_intel_backend(self):
        _, MockAMD, MockIntel, MockNV = self._run_with_driver("i915")
        MockIntel.assert_called_once()
        MockAMD.assert_not_called()

    def test_xe_creates_intel_backend(self):
        _, MockAMD, MockIntel, MockNV = self._run_with_driver("xe")
        MockIntel.assert_called_once()

    def test_nvidia_driver_creates_nvidia_backends(self):
        with (
            patch("detector.glob.glob", return_value=_drm_glob(["card0"])),
            patch("detector.os.path.isdir", return_value=True),
            patch("detector.os.path.islink", return_value=True),
            patch("detector.os.readlink", return_value="../../../../bus/pci/drivers/nvidia"),
            patch("detector._count_nvidia_gpus", return_value=[0, 1]),
            patch("detector.NVIDIABackend") as MockNV,
            patch("detector.AMDBackend"),
            patch("detector.IntelBackend"),
        ):
            det.detect_gpus()
        # Two NVIDIA GPUs → two NVIDIABackend instances
        self.assertEqual(MockNV.call_count, 2)
        MockNV.assert_any_call(0)
        MockNV.assert_any_call(1)

    def test_unknown_driver_is_skipped(self):
        _, MockAMD, MockIntel, MockNV = self._run_with_driver("radeon")
        MockAMD.assert_not_called()
        MockIntel.assert_not_called()
        MockNV.assert_not_called()


# ---------------------------------------------------------------------------
# NVIDIA deduplication (multiple DRM cards, same GPU set)
# ---------------------------------------------------------------------------

class TestNVIDIADeduplication(unittest.TestCase):
    def test_nvidia_gpus_added_only_once_despite_two_drm_cards(self):
        """Two DRM nvidia cards → _count_nvidia_gpus called once → 2 backends."""
        with (
            patch("detector.glob.glob", return_value=_drm_glob(["card0", "card1"])),
            patch("detector.os.path.isdir", return_value=True),
            patch("detector.os.path.islink", return_value=True),
            patch("detector.os.readlink", return_value="../../../../bus/pci/drivers/nvidia"),
            patch("detector._count_nvidia_gpus", return_value=[0, 1]) as mock_count,
            patch("detector.NVIDIABackend") as MockNV,
            patch("detector.AMDBackend"),
            patch("detector.IntelBackend"),
        ):
            det.detect_gpus()
        mock_count.assert_called_once()   # not called twice despite two cards
        self.assertEqual(MockNV.call_count, 2)


# ---------------------------------------------------------------------------
# Fallback: NVIDIA with no DRM node
# ---------------------------------------------------------------------------

class TestNVIDIANoSysfs(unittest.TestCase):
    def test_nvidia_detected_even_without_drm_entry(self):
        """If no DRM card has an nvidia driver but nvidia-smi finds GPUs,
        they must still appear in the result."""
        with (
            patch("detector.glob.glob", return_value=[]),  # no drm entries at all
            patch("detector._count_nvidia_gpus", return_value=[0]),
            patch("detector.NVIDIABackend") as MockNV,
        ):
            backends = det.detect_gpus()
        MockNV.assert_called_once_with(0)
        self.assertEqual(len(backends), 1)


# ---------------------------------------------------------------------------
# Mixed system: Intel iGPU + AMD dGPU
# ---------------------------------------------------------------------------

class TestMixedSystem(unittest.TestCase):
    def test_intel_plus_amd(self):
        def fake_readlink(path: str) -> str:
            if "card0" in path and "card1" not in path:
                return "../../../../bus/pci/drivers/i915"
            return "../../../../bus/pci/drivers/amdgpu"

        with (
            patch("detector.glob.glob", return_value=_drm_glob(["card0", "card1"])),
            patch("detector.os.path.isdir", return_value=True),
            patch("detector.os.path.islink", return_value=True),
            patch("detector.os.readlink", side_effect=fake_readlink),
            patch("detector._count_nvidia_gpus", return_value=[]),
            patch("detector.AMDBackend") as MockAMD,
            patch("detector.IntelBackend") as MockIntel,
        ):
            det.detect_gpus()

        MockIntel.assert_called_once()
        MockAMD.assert_called_once()


# ---------------------------------------------------------------------------
# Sorted order guarantee
# ---------------------------------------------------------------------------

class TestSortedOrder(unittest.TestCase):
    def test_cards_processed_in_sorted_order(self):
        creation_order = []

        def track_amd(*args, **kwargs):
            creation_order.append(args[1])  # card_name
            return MagicMock()

        with (
            patch("detector.glob.glob", return_value=_drm_glob(["card1", "card0", "card2"])),
            patch("detector.os.path.isdir", return_value=True),
            patch("detector.os.path.islink", return_value=True),
            patch("detector.os.readlink", return_value="../../../../bus/pci/drivers/amdgpu"),
            patch("detector._count_nvidia_gpus", return_value=[]),
            patch("detector.AMDBackend", side_effect=track_amd),
        ):
            det.detect_gpus()

        self.assertEqual(creation_order, ["card0", "card1", "card2"])


# ---------------------------------------------------------------------------
# _count_nvidia_gpus — pynvml path
# ---------------------------------------------------------------------------

class TestCountNvidiaGpus(unittest.TestCase):
    def test_pynvml_path_returns_indices(self):
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 3
        with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
            result = det._count_nvidia_gpus()
        self.assertEqual(result, [0, 1, 2])

    def test_smi_fallback_returns_indices(self):
        import subprocess as sp
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "RTX 4090\nRTX 3080\n"

        with (
            patch.dict("sys.modules", {"pynvml": None}),
            patch("detector.subprocess.run", return_value=mock_result),
        ):
            result = det._count_nvidia_gpus()
        self.assertEqual(result, [0, 1])

    def test_returns_empty_when_nothing_found(self):
        with (
            patch.dict("sys.modules", {"pynvml": None}),
            patch("detector.subprocess.run", side_effect=FileNotFoundError),
        ):
            result = det._count_nvidia_gpus()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
