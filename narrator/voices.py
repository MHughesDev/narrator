"""Enumerate offline Windows TTS voices: WinRT ``SpeechSynthesizer.all_voices`` (Narrator catalog) + registry tokens."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ONECORE = r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
_CLASSIC = r"SOFTWARE\Microsoft\Speech\Voices\Tokens"


def _enum_tokens(hive: Any, path: str) -> list[dict[str, str]]:
    import winreg

    out: list[dict[str, str]] = []
    try:
        with winreg.OpenKey(hive, path) as k:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                token_id = name
                display = name
                try:
                    with winreg.OpenKey(k, name) as sk:
                        try:
                            display, _ = winreg.QueryValueEx(sk, "")
                        except OSError:
                            pass
                except OSError:
                    pass
                out.append({"id": token_id, "name": display})
    except OSError as e:
        logger.debug("Registry path %s: %s", path, e)
    return out


def list_installed_voices() -> list[dict[str, str]]:
    """Return voice entries with ``id`` (token) and ``name`` (best-effort display string)."""
    import winreg

    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for hive, base in ((winreg.HKEY_LOCAL_MACHINE, _ONECORE), (winreg.HKEY_LOCAL_MACHINE, _CLASSIC)):
        for row in _enum_tokens(hive, base):
            key = row["id"]
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def list_winrt_voices() -> list[dict[str, str]]:
    """Voices from WinRT ``SpeechSynthesizer.all_voices`` — the same synthesis catalog Narrator uses for TTS."""
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer, VoiceGender

    out: list[dict[str, str]] = []
    vs = SpeechSynthesizer.all_voices
    for i in range(vs.size):
        v = vs.get_at(i)
        g = v.gender
        if g == VoiceGender.MALE:
            gender_s = "male"
        elif g == VoiceGender.FEMALE:
            gender_s = "female"
        else:
            gender_s = "neutral"
        desc = (v.description or "").strip()
        out.append(
            {
                "display_name": v.display_name,
                "id": v.id,
                "language": v.language,
                "description": desc,
                "gender": gender_s,
            }
        )
    out.sort(key=lambda r: (r["language"].lower(), r["display_name"].lower()))
    return out


def _short_voice_id(vid: str) -> str:
    if "\\" in vid:
        return vid.rsplit("\\", 1)[-1]
    return vid


def format_voice_table(
    rows: list[dict[str, str]],
    *,
    winrt_rows: list[dict[str, str]] | None = None,
) -> str:
    """Human-readable list for ``--list-voices``: WinRT (Narrator) voices first, then registry tokens."""

    def _sort_key(r: dict[str, str]) -> tuple[int, str]:
        rid = r.get("id") or ""
        # Prefer OneCore packaged voices over older SAPI-style Desktop tokens
        if rid.startswith("MSTTS_"):
            return (0, rid)
        if rid.startswith("TTS_"):
            return (2, rid)
        return (1, rid)

    sorted_rows = sorted(rows, key=_sort_key)
    lines: list[str] = []

    if winrt_rows is not None:
        lines.extend(
            [
                "WinRT synthesis voices (same catalog as Narrator / Settings; pass display_name to --voice or `voice` in config):",
                "",
            ]
        )
        if not winrt_rows:
            lines.append("  (none)")
        else:
            for r in winrt_rows:
                dn = r.get("display_name") or ""
                lines.append(f"  {dn}")
                lang = r.get("language") or ""
                gen = r.get("gender") or ""
                lines.append(f"    {lang} | {gen}")
                desc = r.get("description") or ""
                if desc and desc != dn:
                    lines.append(f"    ({desc})")
                token = _short_voice_id(r.get("id") or "")
                if token:
                    lines.append(f"    token: {token}")
        lines.extend(["", "---", ""])

    lines.extend(
        [
            "Registry voice tokens (supplementary ids; may overlap WinRT above):",
            "",
            "Tip: OneCore names (MSTTS_*) usually sound better than legacy \"... Desktop\" (TTS_MS_*).",
            "     Add more: Settings - Time & language - Speech - Manage voices (or Narrator - Add natural voices).",
            "",
        ]
    )
    for r in sorted_rows:
        lines.append(f"  {r['id']}")
        if r.get("name") and r["name"] != r["id"]:
            lines.append(f"    ({r['name']})")
    return "\n".join(lines)
