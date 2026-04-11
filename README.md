# 🎙️ Narrator

**Windows only** — hover text, press a key, **hear it read aloud**.  
Another key **dictates into whatever you’re typing in**.

| | Default key | |
|--|-------------|--|
| 🔊 **Speak** | `Ctrl+Alt+S` | Hover → read. Press again to stop. |
| 🎤 **Listen** | `Ctrl+Alt+L` | Focus a box → dictate. Press again to stop. |

Speak and listen are **separate** — they don’t cancel each other.

---

## ⚡ Quick start

1. **Python 3.11–3.14** on Windows — [python.org](https://www.python.org/downloads/) (tick *Add to PATH*).
2. Double‑click **`setup.bat`** in this folder *(first time — can take a while; downloads models)*.
3. Double‑click **`run.bat`** to start.

Done. Change keys or voice in **`%USERPROFILE%\.config\narrator\config.toml`** (copy from **`config.example.toml`**).

---

## 🖥️ Run (after setup)

```bat
run.bat
```

Or with venv active: `python -m narrator`

---

## 📎 Useful links

| | |
|--|--|
| 📖 **Full install & GPU** | [`docs/SETUP.md`](docs/SETUP.md) |
| ⚙️ **All config keys** | [`narrator/settings_schema.md`](narrator/settings_schema.md) |
| 🏗️ **How it’s built** | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| 🐛 **Two voices / overlap?** | [`docs/DEBUG_MULTIPLE_VOICES.md`](docs/DEBUG_MULTIPLE_VOICES.md) |

---

## 📜 License

**MIT** — see [`LICENSE`](LICENSE).
