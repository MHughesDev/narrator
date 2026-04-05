"""Local OpenAI-compatible LLM pass to ready text chunks for TTS (Ollama, LM Studio, vLLM, …)."""

from __future__ import annotations

import functools
import importlib.resources
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

# Default tag for `ollama pull` and for Piper/XTTS when no model is configured (see settings.build_runtime_settings).
DEFAULT_SPEAK_TEXT_LLM_MODEL = "llama3.2:1b"

_BUILTIN_RULES_FILE = "default_speak_text_llm_rules.txt"

_DEFAULT_SYSTEM = (
    "You prepare text for text-to-speech. Follow RULES below exactly. "
    "Output ONLY the cleaned text for this chunk — no quotes, no markdown fences, no preamble or commentary. "
    "Non-narrative excerpts (TOC, reference lists, math blocks, name dumps): output nothing — see RULES section 0. "
    "Do not add facts, numbers, or sources that are not already grounded in the excerpt. "
    "Keep paragraph breaks as single blank lines where appropriate."
)

_BUNDLE_SYSTEM = (
    "You prepare multiple consecutive excerpts from the same document for text-to-speech. "
    "Follow RULES below exactly. "
    "The user message wraps each excerpt in <<<CHUNK n>>> ... <<<END>>> (n starts at 1). "
    "You MUST output the same structure: the same number of blocks, same n, same delimiters. "
    "Inside each wrapper, output ONLY the cleaned speech-ready text for THAT excerpt — or **leave the wrapper body empty** "
    "when RULES 0/13 apply (TOC, citations, math, name lists, etc.); never summarize those aloud. "
    "Use neighboring excerpts only to classify non-body blocks (e.g. TOC, boilerplate); "
    "do not merge wrappers, add titles, or put commentary outside <<<CHUNK>>> / <<<END>>>. "
    "Do not fabricate cross-chunk summaries; table-like excerpts must be emptied per RULES."
)


@functools.lru_cache(maxsize=1)
def _builtin_rules_file_text() -> str:
    """UTF-8 rules shipped next to this package (wheel via package-data)."""
    try:
        return (
            importlib.resources.files("narrator")
            .joinpath(_BUILTIN_RULES_FILE)
            .read_text(encoding="utf-8")
            .strip()
        )
    except (OSError, FileNotFoundError) as e:
        logger.error(
            "Missing builtin speak-text LLM rules %s (%s); RULES section may be empty.",
            _BUILTIN_RULES_FILE,
            e,
        )
        return ""

_CHUNK_MARK_RE = re.compile(r"<<<CHUNK\s*(\d+)\s*>>>(.*?)<<<END>>>", re.IGNORECASE | re.DOTALL)
_CHUNK_HEADER_RE = re.compile(r"<<<\s*CHUNK\s*(\d+)\s*>>>\s*", re.IGNORECASE)


def _normalize_llm_chunk_markers(s: str) -> str:
    """Fix stray spaces in delimiters small models sometimes emit (``<< <CHUNK`` → ``<<<CHUNK``)."""
    return re.sub(r"<<\s*<\s*(?=CHUNK\s*\d)", "<<<", s, flags=re.IGNORECASE)


def _strip_llm_wrapping_fences(s: str) -> str:
    t = s.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_marked_bundle_lenient(raw: str, n: int) -> list[str] | None:
    """Parse first ``n`` chunk bodies by header position (no <<<END>>> required)."""
    matches = list(_CHUNK_HEADER_RE.finditer(raw))
    if len(matches) < n:
        return None
    out: list[str] = []
    for i in range(n):
        start = matches[i].end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[start:end]
        body = re.sub(r"<<<\s*END\s*>>>\s*", "", body, flags=re.I | re.MULTILINE).strip()
        out.append(body)
    return out


def _parse_marked_bundle(raw: str, n: int) -> list[str] | None:
    raw_stripped = _normalize_llm_chunk_markers(_strip_llm_wrapping_fences(raw))
    found: dict[int, str] = {}
    for m in _CHUNK_MARK_RE.finditer(raw_stripped):
        k = int(m.group(1))
        found[k] = m.group(2).strip()
    if len(found) >= n and all(k in found for k in range(1, n + 1)):
        return [found[k] for k in range(1, n + 1)]
    loose = _parse_marked_bundle_lenient(raw_stripped, n)
    if loose is not None:
        logger.info("LLM bundle: parsed with lenient CHUNK boundaries (strict <<<END>>> missing or incomplete)")
    return loose


def _constraints_text_for_llm(settings: "RuntimeSettings") -> str:
    """Hard pipeline limits so small local models see caps alongside RULES."""
    from narrator.speak_chunking import XTTS_MAX_CHARS_PER_SEGMENT, effective_speak_chunk_max_chars

    eng = str(getattr(settings, "speak_engine", "winrt")).strip().lower()
    try:
        scm = int(getattr(settings, "speak_chunk_max_chars", 0) or 0)
    except (TypeError, ValueError):
        scm = 0
    tts_cap = effective_speak_chunk_max_chars(eng, scm)
    mode = str(getattr(settings, "speak_text_llm_mode", "heuristic_then_llm")).strip()
    try:
        bun = int(getattr(settings, "speak_text_llm_bundle_chunks", 1))
    except (TypeError, ValueError):
        bun = 1
    try:
        bmax = int(getattr(settings, "speak_text_llm_bundle_max_chars", 16000))
    except (TypeError, ValueError):
        bmax = 16000
    try:
        mchunk = int(getattr(settings, "speak_text_llm_max_chunk_chars", 6000))
    except (TypeError, ValueError):
        mchunk = 6000
    return (
        "CONSTRAINTS (obey together with RULES; set by the app, not negotiable):\n"
        f"- speak_text_llm_mode={mode!r}: with heuristic_then_llm, upstream preprocess already removed much noise; "
        "with llm_primary, apply RULES 12 and strip aggressively.\n"
        f"- speak_engine={eng!r}: after final chunking, each TTS segment is at most ~{tts_cap} characters "
        f"(XTTS never exceeds ~{XTTS_MAX_CHARS_PER_SEGMENT} chars per synthesis call).\n"
        f"- Bundled LLM requests: up to {bun} <<<CHUNK n>>> blocks per call; "
        f"~{mchunk} chars max per chunk body; ~{bmax} chars soft cap total per request.\n"
        "- Some chunks are intentionally **empty** after cleaning (TOC, reference blocks, equation dumps, name lists). "
        "Do not fill empty slots with summaries; follow RULES 0 and 13.\n"
        "- Do not add facts, numbers, or sources not present in the excerpt. Keep wording concise so it fits segment caps."
    )


def _system_with_rules(settings: "RuntimeSettings", *, bundle: bool) -> str:
    core = _BUNDLE_SYSTEM if bundle else _DEFAULT_SYSTEM
    parts = [core, _constraints_text_for_llm(settings)]
    rules = load_rules_text(settings)
    if rules:
        parts.append("RULES:\n" + rules)
    return "\n\n".join(parts)


def load_rules_text(settings: "RuntimeSettings") -> str:
    """Builtin rules (unless disabled), then inline TOML rules, then optional UTF-8 file."""
    parts: list[str] = []
    if bool(getattr(settings, "speak_text_llm_builtin_rules", True)):
        b = _builtin_rules_file_text().strip()
        if b:
            parts.append(b)
    inline = str(getattr(settings, "speak_text_llm_rules", "") or "").strip()
    if inline:
        parts.append(inline)
    path_s = getattr(settings, "speak_text_llm_rules_file", None)
    if path_s:
        p = Path(str(path_s).strip())
        try:
            if p.is_file():
                parts.append(p.read_text(encoding="utf-8"))
            else:
                logger.warning("speak_text_llm_rules_file not found: %s", p)
        except OSError as e:
            logger.warning("speak_text_llm_rules_file read failed: %s", e)
    return "\n\n".join(parts).strip()


def chat_completion(
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    system_prompt: str,
    user_message: str,
    timeout_s: float,
) -> str:
    """
    POST ``/chat/completions`` (OpenAI-compatible). Returns assistant message content or raises.
    """
    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root = root + "/v1"
    url = root + "/chat/completions"
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.1,
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"LLM HTTP {e.code}: {err_body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM request failed: {e}") from e

    payload = json.loads(raw)
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("LLM response has no choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if content is None:
        raise RuntimeError("LLM response has no message content")
    return str(content).strip()


def _llm_common(settings: "RuntimeSettings") -> tuple[str, str, float, str | None]:
    model = str(getattr(settings, "speak_text_llm_model", "") or "").strip()
    base = str(getattr(settings, "speak_text_llm_base_url", "http://127.0.0.1:11434/v1") or "").strip()
    if not base:
        base = "http://127.0.0.1:11434/v1"
    timeout_s = float(getattr(settings, "speak_text_llm_timeout_s", 120.0))
    timeout_s = max(5.0, min(600.0, timeout_s))
    key = getattr(settings, "speak_text_llm_api_key", None)
    key_s = str(key).strip() if key else None
    return base, model, timeout_s, key_s


def _llm_failure_log(settings: "RuntimeSettings", base: str, model: str, err: BaseException) -> None:
    eng = str(getattr(settings, "speak_engine", "winrt") or "").strip().lower()
    if eng in ("piper", "xtts"):
        logger.error(
            "LLM text-readying failed for speak_engine=%s at %s (%s); using heuristic chunk. "
            "Start Ollama and ensure model %r is pulled.",
            eng,
            base,
            err,
            model,
        )
    else:
        logger.warning("LLM ready failed (%s); using heuristic chunk", err)


def chunk_bundle_ranges(chunks: list[str], settings: "RuntimeSettings") -> list[tuple[int, int]]:
    """
    Partition ``chunks`` into half-open index ranges ``[a, b)`` for bundled LLM calls.
    Respects ``speak_text_llm_bundle_chunks`` (target count) and ``speak_text_llm_bundle_max_chars``.
    """
    try:
        target = int(getattr(settings, "speak_text_llm_bundle_chunks", 1))
    except (TypeError, ValueError):
        target = 1
    target = max(1, min(64, target))
    try:
        max_b = int(getattr(settings, "speak_text_llm_bundle_max_chars", 16000))
    except (TypeError, ValueError):
        max_b = 16000
    max_b = max(1024, min(200_000, max_b))
    try:
        max_per = int(getattr(settings, "speak_text_llm_max_chunk_chars", 6000))
    except (TypeError, ValueError):
        max_per = 6000
    max_per = max(256, min(200_000, max_per))

    n = len(chunks)
    ranges: list[tuple[int, int]] = []
    i = 0
    while i < n:
        j = i
        total = 0
        while j < n and (j - i) < target:
            ln = min(len(chunks[j]), max_per)
            if total + ln > max_b and j > i:
                break
            if total + ln > max_b and j == i:
                j += 1
                break
            total += ln
            j += 1
        if j <= i:
            j = i + 1
        ranges.append((i, j))
        i = j
    return ranges


def ready_chunk_for_speech(chunk: str, settings: "RuntimeSettings") -> str:
    """
    Send one chunk to the local LLM; return ready text. On any failure, returns ``chunk`` unchanged.
    """
    if not chunk.strip():
        return chunk
    base, model, timeout_s, key_s = _llm_common(settings)
    if not model:
        logger.warning("speak_text_llm_model is empty; skipping LLM ready pass")
        return chunk
    max_c = int(getattr(settings, "speak_text_llm_max_chunk_chars", 6000))
    max_c = max(256, min(200_000, max_c))
    truncated = chunk if len(chunk) <= max_c else chunk[:max_c]
    system = _system_with_rules(settings, bundle=False)
    user_msg = (
        "Transform the following chunk for spoken output only.\n\n---\n\n" + truncated + "\n\n---"
    )
    try:
        out = chat_completion(
            base_url=base,
            model=model,
            api_key=key_s,
            system_prompt=system,
            user_message=user_msg,
            timeout_s=timeout_s,
        )
        if not out.strip():
            if not truncated.strip():
                return chunk
            # Intentional omission (RULES 0): TOC, references, math, name dumps — do not re-speak raw noise.
            logger.debug("LLM returned empty for single chunk; omitting segment")
            return ""
        return out
    except Exception as e:
        _llm_failure_log(settings, base, model, e)
        return chunk


def _ready_marked_bundle(bundle: list[str], settings: "RuntimeSettings") -> list[str]:
    """One LLM call for ``bundle`` (len >= 2); returns same length or raises."""
    base, model, timeout_s, key_s = _llm_common(settings)
    if not model:
        raise RuntimeError("empty model")
    n = len(bundle)
    try:
        max_per = int(getattr(settings, "speak_text_llm_max_chunk_chars", 6000))
    except (TypeError, ValueError):
        max_per = 6000
    max_per = max(256, min(200_000, max_per))
    parts: list[str] = []
    for k, piece in enumerate(bundle, start=1):
        t = piece if len(piece) <= max_per else piece[:max_per]
        parts.append(f"<<<CHUNK {k}>>>\n{t}\n<<<END>>>")
    system = _system_with_rules(settings, bundle=True)
    user_msg = (
        f"There are {n} consecutive excerpts in reading order. "
        "Return them with the same <<<CHUNK n>>> / <<<END>>> structure.\n\n"
        + "\n\n".join(parts)
    )
    raw = chat_completion(
        base_url=base,
        model=model,
        api_key=key_s,
        system_prompt=system,
        user_message=user_msg,
        timeout_s=timeout_s,
    )
    parsed = _parse_marked_bundle(raw, n)
    if parsed is None:
        logger.warning(
            "LLM bundle parse failed (expected %d CHUNK blocks); falling back per chunk", n
        )
        raise RuntimeError("bundle parse failed")
    return parsed


def ready_chunks_for_speech(chunks: list[str], settings: "RuntimeSettings") -> list[str]:
    """
    LLM-ready every TTS chunk. When ``speak_text_llm_bundle_chunks`` > 1, sends **bundles** of
    consecutive chunks in one request so the model sees TOC / section context; responses must
    preserve ``<<<CHUNK n>>>`` wrappers.

    The speak worker may call this on slices (e.g. first bundle only) for pipelined playback.
    """
    if not chunks:
        return chunks
    if not bool(getattr(settings, "speak_text_llm_enabled", False)):
        return list(chunks)
    out: list[str] = []
    for a, b in chunk_bundle_ranges(chunks, settings):
        bundle = chunks[a:b]
        if not bundle:
            continue
        if len(bundle) == 1:
            ch0 = bundle[0]
            if settings.verbose:
                logger.debug("LLM ready chunk single (%d chars)", len(ch0))
            out.append(ready_chunk_for_speech(ch0, settings))
            continue
        if settings.verbose:
            logger.debug("LLM ready bundle %d chunks (indices %d..%d)", len(bundle), a, b - 1)
        try:
            out.extend(_ready_marked_bundle(bundle, settings))
        except Exception as e:
            b, m, _, _ = _llm_common(settings)
            if isinstance(e, RuntimeError) and "bundle parse failed" in str(e).lower():
                logger.info(
                    "LLM bundle reply missing or malformed <<<CHUNK>>> markers (%d expected). Per-chunk fallback. "
                    "Default is one chunk per request (speak_text_llm_bundle_chunks=1); use 2–4 only if the model "
                    "reliably returns the same delimiters.",
                    len(bundle),
                )
            else:
                _llm_failure_log(settings, b, m, e)
            logger.info("LLM bundle fallback: per-chunk (%d pieces)", len(bundle))
            for ch in bundle:
                out.append(ready_chunk_for_speech(ch, settings))
    assert len(out) == len(chunks), "internal: chunk count mismatch after LLM bundle"
    return out
