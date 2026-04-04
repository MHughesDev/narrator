# Contributing

- **Issues & PRs:** Use GitHub (or your host) as usual; keep changes focused and match existing style in `narrator/`.
- **Platform:** The app is **Windows-first** (WinRT, UI Automation). CI and full tests should be run on **Windows** when touching speak/listen paths.
- **Setup:** Use **`setup.bat`** or **`python scripts/bootstrap_install.py --auto`** — see [`docs/SETUP.md`](docs/SETUP.md).
- **Optional GPU:** CUDA PyTorch / ONNX GPU are **environment** choices, not separate forks; document any new extras in [`pyproject.toml`](pyproject.toml) and `docs/SETUP.md`.

License: **MIT** (see [`LICENSE`](LICENSE)).
