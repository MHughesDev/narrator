"""
Platform and hardware detection for narrator setup (Windows-first).

Used by bootstrap_install to choose CPU vs CUDA PyTorch and to print a clear summary.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Repo root = parent of scripts/ (used for disk free space on the project drive).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Neural stack (PyTorch + models) benefits from plenty of free disk; warn below this (GiB).
DISK_FREE_WARN_GIB = 15.0


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
    # Expanded (Windows-focused; best-effort elsewhere)
    cpu_name: str | None
    cpu_logical_cores: int | None
    ram_total_gib: float | None
    disk_free_gib: float | None
    disk_checked_path: str | None
    vc_runtime_dll_present: bool | None

    def summary_lines(self) -> list[str]:
        arch = (self.machine or "").lower()
        arch_note = ""
        if arch in ("arm64", "aarch64"):
            arch_note = " — ARM64 Windows: use CPU PyTorch builds; CUDA wheel path is for x64 NVIDIA"

        lines = [
            f"Platform: {self.system} ({self.machine}){arch_note}",
            f"Python: {self.python_version}",
        ]
        if self.cpu_name:
            cores = self.cpu_logical_cores
            core_s = f", {cores} logical cores" if cores is not None else ""
            lines.append(f"CPU: {self.cpu_name}{core_s}")
        elif self.cpu_logical_cores is not None:
            lines.append(f"CPU: ({self.cpu_logical_cores} logical cores)")
        if self.ram_total_gib is not None:
            lines.append(f"RAM: {self.ram_total_gib:.1f} GiB total")
        if self.disk_free_gib is not None and self.disk_checked_path:
            lines.append(
                f"Disk free ({self.disk_checked_path}): {self.disk_free_gib:.1f} GiB"
            )
            if self.disk_free_gib < DISK_FREE_WARN_GIB:
                lines.append(
                    f"  Warning: less than {DISK_FREE_WARN_GIB:.0f} GiB free — neural install + models may fail; "
                    "free space or use profile minimal."
                )
        if self.is_windows:
            lines.append("Windows: yes (full WinRT + UIA stack supported)")
        else:
            lines.append(
                "Windows: no — narrator is developed for Windows; "
                "WinRT packages will not install on this OS."
            )
        if self.vc_runtime_dll_present is False:
            lines.append(
                "VC++ runtime: vcruntime140.dll not found in System32 — "
                "if PyTorch fails to load, install: "
                "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist"
            )
        elif self.vc_runtime_dll_present is True:
            lines.append("VC++ runtime: vcruntime140.dll present (basic check)")
        if self.nvidia_present:
            lines.append(f"NVIDIA GPU: {self.nvidia_gpu_name or 'detected'}")
            if self.nvidia_driver:
                lines.append(f"NVIDIA driver: {self.nvidia_driver}")
        else:
            lines.append("NVIDIA GPU: not detected (CUDA path skipped)")
        return lines


def _python_short() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _windows_memory_total_gib() -> float | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return ms.ullTotalPhys / (1024.0**3)
    except Exception:
        pass
    return None


def _cpu_name_and_cores() -> tuple[str | None, int | None]:
    cores = os.cpu_count()
    name: str | None = None
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor).Name",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0 and (r.stdout or "").strip():
                name = (r.stdout or "").strip().splitlines()[0].strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not name:
        proc = platform.processor()
        if proc and proc.strip():
            name = proc.strip()
    return name, cores


def _repo_disk_free_gib() -> tuple[float | None, str | None]:
    try:
        p = REPO_ROOT.resolve()
        if not p.exists():
            p = Path.cwd().resolve()
        usage = shutil.disk_usage(p)
        return usage.free / (1024.0**3), str(p)
    except OSError:
        return None, None


def _windows_vc_runtime_dll_present() -> bool | None:
    if sys.platform != "win32":
        return None
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    dll = Path(sys_root) / "System32" / "vcruntime140.dll"
    try:
        return dll.is_file()
    except OSError:
        return None


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
    cpu_name, cpu_cores = _cpu_name_and_cores()
    ram_gib = _windows_memory_total_gib()
    disk_free, disk_path = _repo_disk_free_gib()
    vc_ok = _windows_vc_runtime_dll_present()
    return HardwareReport(
        system=sysname,
        machine=platform.machine() or "",
        python_version=_python_short(),
        is_windows=sysname == "Windows",
        nvidia_present=nvidia_ok,
        nvidia_gpu_name=gpu_name,
        nvidia_driver=drv,
        nvidia_smi_path=smi_path,
        cpu_name=cpu_name,
        cpu_logical_cores=cpu_cores,
        ram_total_gib=ram_gib,
        disk_free_gib=disk_free,
        disk_checked_path=disk_path,
        vc_runtime_dll_present=vc_ok,
    )


# PyTorch CUDA wheel index (cu124 works on many recent drivers; override via env if needed).
DEFAULT_TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu124"


def torch_cuda_index_url() -> str:
    import os

    v = (os.environ.get("NARRATOR_TORCH_CUDA_INDEX") or "").strip()
    return v or DEFAULT_TORCH_CUDA_INDEX


def summary_one_line(r: HardwareReport) -> str:
    bits = [f"{r.system} {r.machine}", f"Python {r.python_version}"]
    if r.nvidia_present:
        bits.append(f"NVIDIA: {r.nvidia_gpu_name or 'yes'}")
    else:
        bits.append("NVIDIA: —")
    return " | ".join(bits)


def print_report(r: HardwareReport | None = None, *, verbose: bool | None = None) -> None:
    rep = r or hardware_report()
    if verbose is None:
        from setup_terminal import setup_verbose

        verbose = setup_verbose()
    if verbose:
        print("--- Hardware / environment ---")
        for line in rep.summary_lines():
            print(" ", line)
        print("------------------------------")
    else:
        print(summary_one_line(rep))


def main() -> int:
    print_report(verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
