"""Verify core and optional dependencies after install."""

from __future__ import annotations

import sys


def main() -> int:
    errors: list[str] = []

    def check(label: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            errors.append(f"{label}: {e}")

    def imp_winrt() -> None:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401

    def imp_pynput() -> None:
        import pynput  # noqa: F401

    def imp_uia() -> None:
        import uiautomation  # noqa: F401

    def imp_torch() -> None:
        import torch

        print("torch", torch.__version__, "| CUDA available:", torch.cuda.is_available())
        if torch.cuda.is_available():
            print("  CUDA device:", torch.cuda.get_device_name(0))

    def imp_tts() -> None:
        import TTS  # noqa: F401

    def imp_onnx() -> None:
        import onnxruntime as ort

        print("onnxruntime", ort.__version__, "| providers:", ort.get_available_providers())

    # Neural imports must run before WinRT in this process: otherwise torch fails (WinError 1114 on c10.dll).
    print("Neural TTS (speak-xtts / speak-piper extras):")
    check("torch", imp_torch)
    check("TTS (coqui-tts)", imp_tts)
    check("onnxruntime", imp_onnx)
    if errors:
        for e in errors:
            print("  FAIL", e)
        print("Install: pip install -e \".[speak-xtts,speak-piper]\"", file=sys.stderr)
        neural_errors = list(errors)
    else:
        neural_errors = []
    errors.clear()

    print("Core (required):")
    check("winrt", imp_winrt)
    check("pynput", imp_pynput)
    check("uiautomation", imp_uia)
    if errors:
        for e in errors:
            print("  FAIL", e)
        print("Install: pip install -e .", file=sys.stderr)
        return 1

    print("  OK — WinRT / hotkeys / UIA")

    if neural_errors:
        return 2

    print("  OK — torch / Coqui / onnxruntime")

    try:
        import onnxruntime as ort

        if "CUDAExecutionProvider" in ort.get_available_providers():
            print("  Note: ONNX Runtime has CUDA — Piper can use --piper-cuda")
        else:
            print("  Note: ONNX Runtime CPU — Piper uses CPU unless you install onnxruntime-gpu")
    except Exception:
        pass

    print("OK: environment looks ready for narrator (core + neural TTS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
