"""Queue-driven worker: toggle -> capture -> synthesize -> interruptible play."""

from __future__ import annotations

import logging
import queue
import tempfile
import threading
import time
import winsound
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum, auto
from pathlib import Path

from uiautomation import InitializeUIAutomationInCurrentThread, UninitializeUIAutomationInCurrentThread

from narrator import audio_debug, capture, speech
from narrator.audio_pcm import wav_write_pcm
from narrator.audio_stream_compile import (
    CompiledUtteranceState,
    combined_utterance_label,
    merge_segment_wav_into_state,
)
from narrator.speak_chunking import (
    XTTS_MAX_CHARS_PER_SEGMENT,
    effective_speak_chunk_max_chars,
    extract_chunk_context_tail,
    iter_tts_chunks,
    merge_trailing_short_chunks,
    split_raw_for_streaming_preprocess,
    trim_context_to_synth_budget,
)
from narrator.speak_preprocess import prepare_speak_text_from_settings, prepare_speak_text_minimal
from narrator.speak_text_llm import chunk_bundle_ranges, ready_chunks_for_speech
from narrator.speak_prosody import apply_speak_prosody
from narrator.protocol import SHUTDOWN, SPEAK_RATE_DOWN, SPEAK_RATE_UP, SPEAK_TOGGLE
from narrator.wav_play_win32 import apply_speak_rate_queue_message
from narrator.settings import RuntimeSettings

logger = logging.getLogger(__name__)

WavPathOrBytes = Path | bytes


def _unlink_wav_if_path(p: WavPathOrBytes) -> None:
    if isinstance(p, Path):
        p.unlink(missing_ok=True)


def _prepare_captured_text(raw: str, settings: RuntimeSettings) -> str:
    """Full heuristic preprocess, or minimal strip when ``llm_primary`` mode."""
    if bool(getattr(settings, "speak_text_llm_enabled", False)) and str(
        getattr(settings, "speak_text_llm_mode", "heuristic_then_llm")
    ).strip().lower() == "llm_primary":
        return prepare_speak_text_minimal(raw)
    return prepare_speak_text_from_settings(raw, settings)


def _effective_prefetch_depth(settings: RuntimeSettings) -> int:
    eff = int(getattr(settings, "speak_synth_max_ahead", 0) or 0)
    base = int(getattr(settings, "speak_prefetch_depth", 4))
    return max(1, min(512, eff if eff > 0 else base))


class Phase(Enum):
    IDLE = auto()
    SYNTHESIZING = auto()
    PLAYING = auto()


def _drain_cancel_or_shutdown(q: queue.Queue, settings: RuntimeSettings) -> tuple[bool, bool]:
    cancel = False
    shutdown = False
    try:
        while True:
            m = q.get_nowait()
            if m == SPEAK_TOGGLE:
                cancel = True
            elif m == SHUTDOWN:
                shutdown = True
            elif m in (SPEAK_RATE_UP, SPEAK_RATE_DOWN):
                apply_speak_rate_queue_message(settings, m)
    except queue.Empty:
        pass
    return cancel, shutdown


def _beep_failure() -> None:
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as e:
        logger.debug("MessageBeep: %s", e)


# Producer puts audio tuples; then ``_SPEAK_Q_END``; on failure ``_SPEAK_Q_ERR``.
_SPEAK_Q_END = object()
_SPEAK_Q_ERR = object()


def _drain_ready_queue_unlink(q: queue.Queue) -> None:
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if isinstance(item, tuple) and len(item) >= 1:
            p = item[0]
            if isinstance(p, Path):
                p.unlink(missing_ok=True)


def _blocking_get_ready_segment(
    ready_queue: queue.Queue,
    event_queue: queue.Queue,
    settings: RuntimeSettings,
    stop_event: threading.Event,
) -> object | None | str:
    """
    Wait for the next prefetched segment. Returns ``(Path, label, utterance_text)``, ``_SPEAK_Q_END``,
    ``_SPEAK_Q_ERR``, ``None`` if shutdown, or ``"cancel"`` if the user aborted while waiting.
    """
    while not stop_event.is_set():
        try:
            return ready_queue.get(timeout=0.05)
        except queue.Empty:
            cancel, shutdown = _drain_cancel_or_shutdown(event_queue, settings)
            if shutdown:
                return None
            if cancel:
                stop_event.set()
                return "cancel"
    return None


def _join_prefetch(
    producer_thread: threading.Thread | None,
    ready_queue: queue.Queue,
) -> None:
    if producer_thread is not None:
        producer_thread.join(timeout=600.0)
    _drain_ready_queue_unlink(ready_queue)


def _build_work_items_from_chunks(
    chunks: list[str],
    *,
    settings: RuntimeSettings,
    eff_chunk: int,
    min_floor: int | None,
    seg_idx_global_start: int,
    total_chunks_for_label: int,
    prev_chunk_prosody: str | None,
    streaming_labels: bool,
    piece_counter: list[int],
) -> tuple[list[tuple[str, str, str | None, str]], str | None]:
    """Build synth/play tuples from pre-chunked **preprocessed** text (one prosody pass per chunk)."""
    out: list[tuple[str, str, str | None, str]] = []
    prev = prev_chunk_prosody
    for seg_idx, chunk in enumerate(chunks):
        global_seg = seg_idx_global_start + seg_idx
        prosody = apply_speak_prosody(chunk, settings)
        if not prosody.strip():
            continue
        if settings.speak_engine == "xtts":
            speak_pieces = list(
                iter_tts_chunks(prosody.strip(), eff_chunk, min_chunk_floor=min_floor)
            )
        else:
            speak_pieces = [prosody]
        for piece_idx, prosody_piece in enumerate(speak_pieces):
            if not prosody_piece.strip():
                continue
            if streaming_labels:
                piece_counter[0] += 1
                seg_label = str(piece_counter[0])
            else:
                seg_label = f"{global_seg + 1}/{total_chunks_for_label}"
            if len(speak_pieces) > 1:
                seg_label += f" (piece {piece_idx + 1}/{len(speak_pieces)})"
            utterance_text = prosody_piece
            synth_text = utterance_text
            ctx_prefix: str | None = None
            if (
                bool(getattr(settings, "speak_chunk_context_enabled", False))
                and global_seg > 0
                and piece_idx == 0
                and prev
            ):
                ctx = extract_chunk_context_tail(
                    prev,
                    int(getattr(settings, "speak_chunk_context_max_chars", 120)),
                )
                budget = (
                    XTTS_MAX_CHARS_PER_SEGMENT
                    if settings.speak_engine == "xtts"
                    else 500_000
                )
                ctx = trim_context_to_synth_budget(ctx, utterance_text.strip(), budget)
                if ctx:
                    synth_text = f"{ctx} {utterance_text}".strip()
                    ctx_prefix = ctx
            out.append((synth_text, utterance_text, ctx_prefix, seg_label))
        prev = prosody.strip() if prosody.strip() else None
    return out, prev


def speak_worker_loop(event_queue: queue.Queue, settings: RuntimeSettings) -> None:
    """UI Automation (COM) must be initialized on this thread before ControlFromPoint etc."""
    InitializeUIAutomationInCurrentThread()
    try:
        _speak_worker_loop_impl(event_queue, settings)
    finally:
        UninitializeUIAutomationInCurrentThread()


def _speak_worker_loop_impl(event_queue: queue.Queue, settings: RuntimeSettings) -> None:
    phase = Phase.IDLE

    def set_phase(p: Phase) -> None:
        nonlocal phase
        phase = p
        logger.debug("phase -> %s", p.name)

    while True:
        msg = event_queue.get()
        if msg == SHUTDOWN:
            speech.stop_playback()
            logger.info("Speak worker shutdown")
            return
        if msg in (SPEAK_RATE_UP, SPEAK_RATE_DOWN):
            apply_speak_rate_queue_message(settings, msg)
            continue
        if msg != SPEAK_TOGGLE:
            continue

        set_phase(Phase.SYNTHESIZING)
        raw = capture.capture_at_cursor()
        if not raw:
            logger.warning("No text to speak — hover over content with a UIA text provider and try again.")
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
            continue

        eff_chunk = effective_speak_chunk_max_chars(settings.speak_engine, settings.speak_chunk_max_chars)
        min_floor = 200 if settings.speak_engine == "xtts" else None
        eff_for_budget = eff_chunk if eff_chunk > 0 else 8000
        k_pre = max(1, int(getattr(settings, "speak_preprocess_initial_chunks", 3)))
        raw_stripped = raw.strip()
        budget_raw = min(len(raw_stripped), max(eff_for_budget * k_pre, 8000))
        raw_prefix, raw_suffix = split_raw_for_streaming_preprocess(raw_stripped, budget_raw)
        use_streaming = bool(getattr(settings, "speak_preprocess_streaming", True)) and bool(raw_suffix)

        work_items: list[tuple[str, str, str | None, str]] = []
        work_items_lock = threading.Lock()
        piece_counter = [0]
        suffix_done = threading.Event()
        suffix_failed = threading.Event()
        suffix_thread: threading.Thread | None = None
        prefix_llm_done = threading.Event()
        prefix_llm_failed = threading.Event()
        prefix_llm_thread: threading.Thread | None = None
        last_prev_shared: list[str | None] = [None]
        prefetch_dynamic = False
        text: str = ""

        if use_streaming:
            text_prefix = _prepare_captured_text(raw_prefix, settings)
            if not text_prefix.strip():
                use_streaming = False
            else:
                text = text_prefix
                if settings.verbose:
                    logger.debug(
                        "Speak preprocess streaming: prefix %d raw -> %d preprocessed chars; "
                        "suffix %d raw chars (parallel)",
                        len(raw_prefix),
                        len(text_prefix),
                        len(raw_suffix),
                    )
                heur_chunks = merge_trailing_short_chunks(
                    list(iter_tts_chunks(text_prefix, eff_chunk, min_chunk_floor=min_floor)),
                    eff_chunk,
                )
                llm_on = bool(getattr(settings, "speak_text_llm_enabled", False))
                if not heur_chunks:
                    use_streaming = False
                elif not llm_on:
                    w_prefix, last_prev = _build_work_items_from_chunks(
                        heur_chunks,
                        settings=settings,
                        eff_chunk=eff_chunk,
                        min_floor=min_floor,
                        seg_idx_global_start=0,
                        total_chunks_for_label=len(heur_chunks),
                        prev_chunk_prosody=None,
                        streaming_labels=True,
                        piece_counter=piece_counter,
                    )
                    work_items = w_prefix
                    if not work_items:
                        use_streaming = False
                    else:
                        chunks_prefix_len = len(heur_chunks)
                        last_prev_shared[0] = last_prev
                        prefix_llm_done.set()

                        def _suffix_runner() -> None:
                            try:
                                ts = _prepare_captured_text(raw_suffix, settings)
                                if not ts.strip():
                                    return
                                ch2 = merge_trailing_short_chunks(
                                    list(iter_tts_chunks(ts, eff_chunk, min_chunk_floor=min_floor)),
                                    eff_chunk,
                                )
                                ch2 = ready_chunks_for_speech(ch2, settings)
                                extra, _ = _build_work_items_from_chunks(
                                    ch2,
                                    settings=settings,
                                    eff_chunk=eff_chunk,
                                    min_floor=min_floor,
                                    seg_idx_global_start=chunks_prefix_len,
                                    total_chunks_for_label=len(ch2),
                                    prev_chunk_prosody=last_prev_shared[0],
                                    streaming_labels=True,
                                    piece_counter=piece_counter,
                                )
                                with work_items_lock:
                                    work_items.extend(extra)
                            except Exception:
                                logger.exception("Speak preprocess: suffix pass failed")
                                suffix_failed.set()
                            finally:
                                suffix_done.set()

                        suffix_thread = threading.Thread(
                            target=_suffix_runner,
                            name="narrator-speak-preprocess-suffix",
                            daemon=True,
                        )
                        suffix_thread.start()
                        prefetch_dynamic = True
                else:
                    llm_ranges = chunk_bundle_ranges(heur_chunks, settings)
                    a0, b0 = llm_ranges[0]
                    first_ready = ready_chunks_for_speech(heur_chunks[a0:b0], settings)
                    if not any(s.strip() for s in first_ready):
                        use_streaming = False
                    else:
                        w_prefix, last_prev = _build_work_items_from_chunks(
                            first_ready,
                            settings=settings,
                            eff_chunk=eff_chunk,
                            min_floor=min_floor,
                            seg_idx_global_start=a0,
                            total_chunks_for_label=len(heur_chunks),
                            prev_chunk_prosody=None,
                            streaming_labels=True,
                            piece_counter=piece_counter,
                        )
                        work_items = w_prefix
                        if not work_items:
                            use_streaming = False
                        else:
                            chunks_prefix_len = len(heur_chunks)
                            last_prev_shared[0] = last_prev
                            if len(llm_ranges) > 1:

                                def _prefix_llm_tail() -> None:
                                    try:
                                        lp = last_prev_shared[0]
                                        for a, b in llm_ranges[1:]:
                                            ready_part = ready_chunks_for_speech(
                                                heur_chunks[a:b], settings
                                            )
                                            with work_items_lock:
                                                extra, lp = _build_work_items_from_chunks(
                                                    ready_part,
                                                    settings=settings,
                                                    eff_chunk=eff_chunk,
                                                    min_floor=min_floor,
                                                    seg_idx_global_start=a,
                                                    total_chunks_for_label=chunks_prefix_len,
                                                    prev_chunk_prosody=lp,
                                                    streaming_labels=True,
                                                    piece_counter=piece_counter,
                                                )
                                                work_items.extend(extra)
                                                last_prev_shared[0] = lp
                                    except Exception:
                                        logger.exception("Speak LLM: prefix tail failed")
                                        prefix_llm_failed.set()
                                    finally:
                                        prefix_llm_done.set()

                                prefix_llm_thread = threading.Thread(
                                    target=_prefix_llm_tail,
                                    name="narrator-speak-llm-prefix-tail",
                                    daemon=True,
                                )
                                prefix_llm_thread.start()
                            else:
                                prefix_llm_done.set()

                            def _suffix_runner() -> None:
                                try:
                                    ts = _prepare_captured_text(raw_suffix, settings)
                                    if not ts.strip():
                                        if prefix_llm_thread is not None:
                                            prefix_llm_done.wait(timeout=600.0)
                                        return
                                    ch2 = merge_trailing_short_chunks(
                                        list(iter_tts_chunks(ts, eff_chunk, min_chunk_floor=min_floor)),
                                        eff_chunk,
                                    )
                                    if prefix_llm_thread is not None:
                                        if not prefix_llm_done.wait(timeout=600.0):
                                            logger.warning(
                                                "Speak LLM: prefix tail wait timed out before suffix build"
                                            )
                                            suffix_failed.set()
                                            return
                                        if prefix_llm_failed.is_set():
                                            suffix_failed.set()
                                            return
                                    ch2 = ready_chunks_for_speech(ch2, settings)
                                    extra, _ = _build_work_items_from_chunks(
                                        ch2,
                                        settings=settings,
                                        eff_chunk=eff_chunk,
                                        min_floor=min_floor,
                                        seg_idx_global_start=chunks_prefix_len,
                                        total_chunks_for_label=len(ch2),
                                        prev_chunk_prosody=last_prev_shared[0],
                                        streaming_labels=True,
                                        piece_counter=piece_counter,
                                    )
                                    with work_items_lock:
                                        work_items.extend(extra)
                                except Exception:
                                    logger.exception("Speak preprocess: suffix pass failed")
                                    suffix_failed.set()
                                finally:
                                    suffix_done.set()

                            suffix_thread = threading.Thread(
                                target=_suffix_runner,
                                name="narrator-speak-preprocess-suffix",
                                daemon=True,
                            )
                            suffix_thread.start()
                            prefetch_dynamic = True

        if not use_streaming:
            text = _prepare_captured_text(raw, settings)
            if not text:
                logger.warning(
                    "No text left after speak preprocessing — hover over readable prose and try again."
                )
                if settings.beep_on_failure:
                    _beep_failure()
                set_phase(Phase.IDLE)
                continue
            if text != raw and settings.verbose:
                logger.debug("Speak preprocess: %d -> %d chars", len(raw), len(text))

            chunks = list(iter_tts_chunks(text, eff_chunk, min_chunk_floor=min_floor))
            chunks = merge_trailing_short_chunks(chunks, eff_chunk)
            llm_on = bool(getattr(settings, "speak_text_llm_enabled", False))
            if not chunks:
                logger.warning(
                    "No speak segments after chunking — hover over readable prose and try again."
                )
                if settings.beep_on_failure:
                    _beep_failure()
                set_phase(Phase.IDLE)
                continue

            if len(chunks) > 1:
                xtts_note = ""
                if settings.speak_engine == "xtts" and eff_chunk != settings.speak_chunk_max_chars:
                    xtts_note = f"; XTTS capped at {eff_chunk} chars/segment (Coqui en tokenizer ~250 chars; stay under to avoid truncation/GPU errors)"
                elif settings.speak_engine == "xtts":
                    xtts_note = f"; XTTS max {eff_chunk} chars/segment"
                logger.info(
                    "Long document: %d characters in %d segment(s) (speak_chunk_max_chars=%s%s).",
                    len(text),
                    len(chunks),
                    settings.speak_chunk_max_chars or "off",
                    xtts_note,
                )

            if not llm_on:
                work_items, _ = _build_work_items_from_chunks(
                    chunks,
                    settings=settings,
                    eff_chunk=eff_chunk,
                    min_floor=min_floor,
                    seg_idx_global_start=0,
                    total_chunks_for_label=len(chunks),
                    prev_chunk_prosody=None,
                    streaming_labels=False,
                    piece_counter=piece_counter,
                )
            else:
                ns_ranges = chunk_bundle_ranges(chunks, settings)
                a0, b0 = ns_ranges[0]
                first_ready = ready_chunks_for_speech(chunks[a0:b0], settings)
                work_items, last_prev = _build_work_items_from_chunks(
                    first_ready,
                    settings=settings,
                    eff_chunk=eff_chunk,
                    min_floor=min_floor,
                    seg_idx_global_start=a0,
                    total_chunks_for_label=len(chunks),
                    prev_chunk_prosody=None,
                    streaming_labels=False,
                    piece_counter=piece_counter,
                )
                if work_items:
                    last_prev_shared[0] = last_prev
                    if len(ns_ranges) > 1:

                        def _prefix_llm_tail_ns() -> None:
                            try:
                                lp = last_prev_shared[0]
                                for a, b in ns_ranges[1:]:
                                    ready_part = ready_chunks_for_speech(chunks[a:b], settings)
                                    with work_items_lock:
                                        extra, lp = _build_work_items_from_chunks(
                                            ready_part,
                                            settings=settings,
                                            eff_chunk=eff_chunk,
                                            min_floor=min_floor,
                                            seg_idx_global_start=a,
                                            total_chunks_for_label=len(chunks),
                                            prev_chunk_prosody=lp,
                                            streaming_labels=False,
                                            piece_counter=piece_counter,
                                        )
                                        work_items.extend(extra)
                                        last_prev_shared[0] = lp
                            except Exception:
                                logger.exception("Speak LLM: prefix tail failed (non-streaming)")
                                prefix_llm_failed.set()
                            finally:
                                prefix_llm_done.set()

                        prefix_llm_thread = threading.Thread(
                            target=_prefix_llm_tail_ns,
                            name="narrator-speak-llm-prefix-tail",
                            daemon=True,
                        )
                        prefix_llm_thread.start()
                    else:
                        prefix_llm_done.set()

            if prefix_llm_thread is None:
                prefix_llm_done.set()

            if not work_items:
                logger.warning(
                    "No speak segments after chunking — hover over readable prose and try again."
                )
                if settings.beep_on_failure:
                    _beep_failure()
                set_phase(Phase.IDLE)
                continue

            suffix_done.set()
        else:
            if len(work_items) > 0:
                xtts_note = ""
                if settings.speak_engine == "xtts" and eff_chunk != settings.speak_chunk_max_chars:
                    xtts_note = f"; XTTS capped at {eff_chunk} chars/segment (Coqui en tokenizer ~250 chars; stay under to avoid truncation/GPU errors)"
                elif settings.speak_engine == "xtts":
                    xtts_note = f"; XTTS max {eff_chunk} chars/segment"
                logger.info(
                    "Long document (streaming preprocess): %d raw chars; first bundle ready; more segments load in background (speak_chunk_max_chars=%s%s).",
                    len(raw_stripped),
                    settings.speak_chunk_max_chars or "off",
                    xtts_note,
                )

        if not work_items:
            logger.warning(
                "No speakable text after prosody on any segment — hover over readable prose and try again."
            )
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
            continue

        if prefix_llm_thread is not None:
            prefetch_dynamic = True

        any_played = False
        depth = _effective_prefetch_depth(settings)
        ready_queue: queue.Queue = queue.Queue(maxsize=depth)
        stop_prefetch = threading.Event()
        producer_thread: threading.Thread | None = None
        keep_mem = bool(getattr(settings, "speak_keep_wav_in_memory", False))
        synth_workers = max(1, int(getattr(settings, "speak_synth_worker_threads", 1)))

        def _synthesize_segment_to_item(idx: int) -> tuple[WavPathOrBytes, str, str] | None:
            with work_items_lock:
                synth_t, utterance_t, ctx_t, seg_label = work_items[idx]
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            wav_path = Path(tmp.name)
            if not speech.synthesize_to_path_prefetch(
                synth_t, wav_path, settings, context_prefix=ctx_t
            ):
                try:
                    wav_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            if keep_mem:
                try:
                    data = wav_path.read_bytes()
                finally:
                    wav_path.unlink(missing_ok=True)
                return (data, seg_label, utterance_t)
            return (wav_path, seg_label, utterance_t)

        def _run_prefetch_producer() -> None:
            if not prefetch_dynamic:
                n = len(work_items)
                if n <= 1:
                    try:
                        ready_queue.put(_SPEAK_Q_END, timeout=2.0)
                    except Exception:
                        pass
                    return
                indices = list(range(1, n))
                use_parallel = synth_workers > 1

                def _emit_one(idx: int) -> bool:
                    if stop_prefetch.is_set():
                        return False
                    item = _synthesize_segment_to_item(idx)
                    if item is None:
                        try:
                            ready_queue.put(_SPEAK_Q_ERR, timeout=2.0)
                        except Exception:
                            pass
                        return False
                    while True:
                        if stop_prefetch.is_set():
                            p = item[0]
                            if isinstance(p, Path):
                                p.unlink(missing_ok=True)
                            return False
                        try:
                            ready_queue.put(item, timeout=0.5)
                            break
                        except queue.Full:
                            continue
                    return True

                if use_parallel and len(indices) > 1:
                    w = min(synth_workers, len(indices))
                    with ThreadPoolExecutor(max_workers=w) as ex:
                        futs = [ex.submit(_synthesize_segment_to_item, i) for i in indices]
                        for fut in futs:
                            if stop_prefetch.is_set():
                                return
                            item = fut.result()
                            if item is None:
                                try:
                                    ready_queue.put(_SPEAK_Q_ERR, timeout=2.0)
                                except Exception:
                                    pass
                                return
                            while True:
                                if stop_prefetch.is_set():
                                    p = item[0]
                                    if isinstance(p, Path):
                                        p.unlink(missing_ok=True)
                                    return
                                try:
                                    ready_queue.put(item, timeout=0.5)
                                    break
                                except queue.Full:
                                    continue
                else:
                    for idx in indices:
                        if not _emit_one(idx):
                            return
                try:
                    ready_queue.put(_SPEAK_Q_END, timeout=2.0)
                except Exception:
                    pass
                return
            idx = 1
            while True:
                if stop_prefetch.is_set():
                    return
                if suffix_failed.is_set() or prefix_llm_failed.is_set():
                    try:
                        ready_queue.put(_SPEAK_Q_ERR, timeout=2.0)
                    except Exception:
                        pass
                    return
                with work_items_lock:
                    n = len(work_items)
                if idx < n:
                    item = _synthesize_segment_to_item(idx)
                    if item is None:
                        try:
                            ready_queue.put(_SPEAK_Q_ERR, timeout=2.0)
                        except Exception:
                            pass
                        return
                    while True:
                        if stop_prefetch.is_set():
                            p = item[0]
                            if isinstance(p, Path):
                                p.unlink(missing_ok=True)
                            return
                        try:
                            ready_queue.put(item, timeout=0.5)
                            break
                        except queue.Full:
                            continue
                    idx += 1
                    continue
                if (
                    prefix_llm_done.is_set()
                    and suffix_done.is_set()
                    and idx >= n
                ):
                    try:
                        ready_queue.put(_SPEAK_Q_END, timeout=2.0)
                    except Exception:
                        pass
                    return

                time.sleep(0.015)

        set_phase(Phase.SYNTHESIZING)
        tmp0 = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp0.close()
        wav_path = Path(tmp0.name)
        synth0, utterance0, ctx0, seg_label = work_items[0]
        ok, shutdown_now = speech.synthesize_with_queue_cancel(
            synth0, wav_path, settings, event_queue, context_prefix=ctx0
        )
        if shutdown_now:
            speech.stop_playback()
            wav_path.unlink(missing_ok=True)
            logger.info("Speak worker shutdown")
            set_phase(Phase.IDLE)
            continue
        if not ok:
            wav_path.unlink(missing_ok=True)
            set_phase(Phase.IDLE)
            logger.warning(
                "Synthesis failed — hover over readable prose and try again."
            )
            if settings.beep_on_failure:
                _beep_failure()
            continue

        cancel, do_shutdown = _drain_cancel_or_shutdown(event_queue, settings)
        if do_shutdown:
            speech.stop_playback()
            wav_path.unlink(missing_ok=True)
            logger.info("Speak worker shutdown")
            set_phase(Phase.IDLE)
            continue
        if cancel:
            logger.info("Cancelled before playback")
            wav_path.unlink(missing_ok=True)
            set_phase(Phase.IDLE)
            continue

        compile_mode = bool(getattr(settings, "speak_audio_stream_compile", True)) and len(work_items) > 1

        if compile_mode:
            state = CompiledUtteranceState()
            try:
                merge_segment_wav_into_state(state, wav_path, settings)
            except Exception as e:
                logger.error("Speak stream compile: first segment merge failed: %s", e)
                wav_path.unlink(missing_ok=True)
                set_phase(Phase.IDLE)
                if settings.beep_on_failure:
                    _beep_failure()
                continue
            wav_path.unlink(missing_ok=True)

            def _compile_synthesize_rest() -> bool:
                """Sequential synth+merge (ordered), same engines as prefetch — VoxCPM-style concat stream."""
                idx = 1
                while True:
                    cancel_c, shut_c = _drain_cancel_or_shutdown(event_queue, settings)
                    if shut_c:
                        return False
                    if cancel_c:
                        return False
                    if suffix_failed.is_set() or prefix_llm_failed.is_set():
                        return False
                    with work_items_lock:
                        n = len(work_items)
                    if idx < n:
                        tmp_c = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                        tmp_c.close()
                        pth = Path(tmp_c.name)
                        synth_t, _utt, ctx_t, _lab = work_items[idx]
                        ok_c, shut_c = speech.synthesize_with_queue_cancel(
                            synth_t, pth, settings, event_queue, context_prefix=ctx_t
                        )
                        if shut_c:
                            pth.unlink(missing_ok=True)
                            return False
                        if not ok_c:
                            pth.unlink(missing_ok=True)
                            return False
                        try:
                            merge_segment_wav_into_state(state, pth, settings)
                        except Exception as e:
                            logger.error("Speak stream compile: merge failed at segment %d: %s", idx, e)
                            pth.unlink(missing_ok=True)
                            return False
                        pth.unlink(missing_ok=True)
                        idx += 1
                        continue
                    if prefetch_dynamic:
                        if prefix_llm_done.is_set() and suffix_done.is_set() and idx >= n:
                            break
                        time.sleep(0.015)
                        continue
                    break
                return True

            compile_ok = True
            if not prefetch_dynamic:
                for idx in range(1, len(work_items)):
                    cancel_c, shut_c = _drain_cancel_or_shutdown(event_queue, settings)
                    if shut_c:
                        speech.stop_playback()
                        logger.info("Speak worker shutdown")
                        set_phase(Phase.IDLE)
                        compile_ok = False
                        break
                    if cancel_c:
                        set_phase(Phase.IDLE)
                        compile_ok = False
                        break
                    tmp_c = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp_c.close()
                    pth = Path(tmp_c.name)
                    synth_t, _utt, ctx_t, _lab = work_items[idx]
                    ok_c, shut_c = speech.synthesize_with_queue_cancel(
                        synth_t, pth, settings, event_queue, context_prefix=ctx_t
                    )
                    if shut_c:
                        pth.unlink(missing_ok=True)
                        speech.stop_playback()
                        logger.info("Speak worker shutdown")
                        set_phase(Phase.IDLE)
                        compile_ok = False
                        break
                    if not ok_c:
                        pth.unlink(missing_ok=True)
                        set_phase(Phase.IDLE)
                        logger.warning(
                            "Synthesis failed — hover over readable prose and try again."
                        )
                        if settings.beep_on_failure:
                            _beep_failure()
                        compile_ok = False
                        break
                    try:
                        merge_segment_wav_into_state(state, pth, settings)
                    except Exception as e:
                        logger.error("Speak stream compile: merge failed at segment %d: %s", idx, e)
                        pth.unlink(missing_ok=True)
                        set_phase(Phase.IDLE)
                        if settings.beep_on_failure:
                            _beep_failure()
                        compile_ok = False
                        break
                    pth.unlink(missing_ok=True)
            else:
                compile_ok = _compile_synthesize_rest()

            if not compile_ok:
                speech.stop_playback()
                set_phase(Phase.IDLE)
                continue

            tmp_f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_f.close()
            wav_path = Path(tmp_f.name)
            try:
                wav_write_pcm(
                    wav_path,
                    state.channels,
                    state.sampwidth,
                    state.framerate,
                    state.pcm,
                )
            except Exception as e:
                logger.error("Speak stream compile: write WAV failed: %s", e)
                wav_path.unlink(missing_ok=True)
                set_phase(Phase.IDLE)
                if settings.beep_on_failure:
                    _beep_failure()
                continue
            if settings.verbose:
                logger.debug(
                    "Speak audio stream compile: merged %d segments into one clip",
                    state.segments_merged,
                )

        if (not compile_mode) and (len(work_items) > 1 or prefetch_dynamic):
            producer_thread = threading.Thread(
                target=_run_prefetch_producer,
                name="narrator-speak-prefetch",
                daemon=True,
            )
            producer_thread.start()
            if settings.verbose:
                logger.debug(
                    "Speak prefetch queue depth=%d (%d segments initial, prefetch_dynamic=%s)",
                    depth,
                    len(work_items),
                    prefetch_dynamic,
                )

        playback_items = (
            [(None, combined_utterance_label(work_items), None, "compiled")]
            if compile_mode
            else work_items
        )

        seg_idx = 0
        while seg_idx < len(playback_items):
            any_played = True
            set_phase(Phase.PLAYING)
            _, utterance_text, _, seg_label = playback_items[seg_idx]
            if compile_mode:
                logger.info("Playing compiled stream (%d chars)", len(utterance_text))
            elif len(playback_items) > 1:
                logger.info("Playing segment %s (%d chars)", seg_label, len(utterance_text))
            else:
                logger.info("Playing (%d chars)", len(utterance_text))

            if audio_debug.is_enabled():
                first_line = utterance_text.split("\n", 1)[0].strip().replace("\r", "")
                if len(first_line) > 200:
                    first_line = first_line[:197] + "..."
                n_lines = utterance_text.count("\n") + 1
                audio_debug.log_kv(
                    "speak text to TTS (direct string output)",
                    n_text_lines=n_lines,
                    text_chars=len(utterance_text),
                    segment=seg_label,
                    first_line_preview=first_line or "(empty)",
                )
            audio_debug.log_kv(
                "worker play_wav_interruptible call",
                text_chars=len(utterance_text),
                wav_path=str(wav_path) if isinstance(wav_path, Path) else "(bytes)",
                segment=seg_label,
            )
            cross_carry: bytes | None = None
            played_through = False
            while True:
                play_result = speech.play_wav_interruptible(
                    wav_path,
                    event_queue,
                    settings=settings,
                    rate_baked_in_wav=float(settings.speaking_rate),
                    utterance_text=utterance_text,
                    crossfade_prev_pcm=None if compile_mode else cross_carry,
                )
                if not compile_mode:
                    cross_carry = play_result.crossfade_tail_pcm
                if play_result.resynth_remainder_text:
                    utterance_text = play_result.resynth_remainder_text
                    _unlink_wav_if_path(wav_path)
                    tmp_rs = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp_rs.close()
                    wav_path = Path(tmp_rs.name)
                    ok_rs, shutdown_rs = speech.synthesize_with_queue_cancel(
                        utterance_text, wav_path, settings, event_queue, context_prefix=None
                    )
                    if shutdown_rs:
                        speech.stop_playback()
                        wav_path.unlink(missing_ok=True)
                        stop_prefetch.set()
                        _join_prefetch(producer_thread, ready_queue)
                        logger.info("Speak worker shutdown")
                        set_phase(Phase.IDLE)
                        return
                    if not ok_rs:
                        wav_path.unlink(missing_ok=True)
                        played_through = False
                        break
                    continue
                played_through = play_result.played_full_clip
                break
            _unlink_wav_if_path(wav_path)
            audio_debug.log_kv(
                "worker play_wav_interruptible returned",
                wav_path=str(wav_path) if isinstance(wav_path, Path) else "(bytes)",
                segment=seg_label,
            )

            seg_idx += 1
            if seg_idx >= len(playback_items):
                if compile_mode or not prefetch_dynamic:
                    break
                if suffix_done.is_set() and prefix_llm_done.is_set():
                    break

            cancel, do_shutdown = _drain_cancel_or_shutdown(event_queue, settings)
            if do_shutdown:
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                speech.stop_playback()
                logger.info("Speak worker shutdown")
                set_phase(Phase.IDLE)
                return
            if not played_through:
                logger.info("Playback stopped; remaining speak segments skipped")
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                set_phase(Phase.IDLE)
                break
            if cancel:
                logger.info("Cancelled during playback")
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                set_phase(Phase.IDLE)
                break

            set_phase(Phase.SYNTHESIZING)
            nxt = _blocking_get_ready_segment(ready_queue, event_queue, settings, stop_prefetch)
            if nxt is None:
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                speech.stop_playback()
                logger.info("Speak worker shutdown")
                set_phase(Phase.IDLE)
                return
            if nxt == "cancel":
                logger.info("Cancelled while waiting for next segment")
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                set_phase(Phase.IDLE)
                break

            if nxt is _SPEAK_Q_ERR:
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                set_phase(Phase.IDLE)
                break

            if nxt is _SPEAK_Q_END:
                logger.warning("Speak prefetch queue ended early (missing segments)")
                stop_prefetch.set()
                _join_prefetch(producer_thread, ready_queue)
                set_phase(Phase.IDLE)
                break

            wav_path, seg_label, utterance_text = nxt  # type: ignore[misc]

        stop_prefetch.set()
        _join_prefetch(producer_thread, ready_queue)
        set_phase(Phase.IDLE)

        if not any_played:
            logger.warning(
                "No speakable text after prosody on any segment — hover over readable prose and try again."
            )
            if settings.beep_on_failure:
                _beep_failure()
            set_phase(Phase.IDLE)
