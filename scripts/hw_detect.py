"""
Platform and hardware detection for narrator setup (Windows-first).

Used by bootstrap_install to choose CPU vs CUDA PyTorch and to print a clear summary.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareReport:
    system: str
    machine: str
    python_version: str
    is_windows: bool
    nvidia_present: bool
    nvidia_gpu_name: str | None
    nvidia_driver: str | None
    nvidia_smi_path: str | None

    def summary_lines(self) -> list[str]:
        lines = [
            f"Platform: {self.system} ({self.machine})",
            f"Python: {self.python_version}",
        ]
        if self.is_windows:
            lines.append("Windows: yes (full WinRT + UIA stack supported)")
        else:
            lines.append(
                "Windows: no — narrator is developed for Windows; "
                "WinRT packages will not install on this OS."
            )
        if self.nvidia_present:
            lines.append(f"NVIDIA GPU: {self.nvidia_gpu_name or 'detected'}")
            if self.nvidia_driver:
                lines.append(f"NVIDIA driver: {self.nvidia_driver}")
        else:
            lines.append("NVIDIA GPU: not detected (CUDA path skipped)")
        return lines


def _python_short() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def detect_nvidia_via_smi() -> tuple[bool, str | None, str | None, str | None]:
    """Return (present, gpu_name, driver_version, smi_path)."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False, None, None, None
    try:
        r = subprocess.run(
            [smi, "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, None, None, smi
    if r.returncode != 0 or not (r.stdout or "").strip():
        return False, None, None, smi
    line = (r.stdout.strip().splitlines() or [""])[0]
    # "NVIDIA GeForce RTX 3080, 581.80"
    parts = [p.strip() for p in line.split(",", 1)]
    name = parts[0] if parts else None
    drv = parts[1] if len(parts) > 1 else None
    return True, name, drv, smi


def hardware_report() -> HardwareReport:
    sysname = platform.system()
    nvidia_ok, gpu_name, drv, smi_path = detect_nvidia_via_smi()
    return HardwareReport(
        system=sysname,
        machine=platform.machine() or "",
        python_version=_python_short(),
        is_windows=sysname == "Windows",
        nvidia_present=nvidia_ok,
        nvidia_gpu_name=gpu_name,
        nvidia_driver=drv,
        nvidia_smi_path=smi_path,
    )


# PyTorch CUDA wheel index (cu124 works on many recent drivers; override via env if needed).
DEFAULT_TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu124"


def torch_cuda_index_url() -> str:
    import os

    v = (os.environ.get("NARRATOR_TORCH_CUDA_INDEX") or "").strip()
    return v or DEFAULT_TORCH_CUDA_INDEX


def print_report(r: HardwareReport | None = None) -> None:
    rep = r or hardware_report()
    print("--- Hardware / environment ---")
    for line in rep.summary_lines():
        print(" ", line)
    print("------------------------------")


def main() -> int:
    print_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
