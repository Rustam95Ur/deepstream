"""
GStreamer RTSP debug probe for diagnostics.

Uses rtspsrc / pad-added / H264|H265 branch logic, drains into ``fakesink``
and collects bus messages instead of writing a file.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.ds.rtsp import sanitize_rtsp_url

logger = logging.getLogger(__name__)

RTSP_LATENCY_MS = 500
# GstRtsp.RTSPLowerTrans.TCP — resolved lazily; numeric fallback is 4.
RTSP_PROTOCOLS_TCP = 4
STARTUP_TIMEOUT_SEC = 5.0

DEFAULT_PROBE_DURATION_SEC = 10.0
MAX_PROBE_DURATION_SEC = 30.0
MIN_PROBE_DURATION_SEC = 3.0

_gi_bundle = None


def _gi():
    """Lazy Gst + GLib import so the module loads without PyGObject."""
    global _gi_bundle, RTSP_PROTOCOLS_TCP
    if _gi_bundle is not None:
        return _gi_bundle

    try:
        import gi
    except ImportError as exc:
        raise ImportError(
            "Для GStreamer-probe нужен PyGObject (gi) и системный GStreamer."
        ) from exc

    gi.require_version("Gst", "1.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import GLib, Gst

    Gst.init(None)
    _gi_bundle = (Gst, GLib)
    return _gi_bundle


def _format_gstreamer_error(
    err, debug: str | None = None, *, max_len: int = 2000
) -> str:
    parts: list[str] = []
    err_text = str(err).strip()
    if err_text:
        parts.append(err_text)
    if debug:
        debug_text = debug.strip()
        if debug_text:
            parts.append(debug_text)
    text = "\n".join(parts)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def mask_rtsp_credentials(rtsp_url: str) -> str:
    """Hide password in RTSP URL for display."""
    s = (rtsp_url or "").strip()
    if not s.lower().startswith("rtsp://") or "@" not in s:
        return s
    rest = s[7:]
    slash = rest.find("/")
    if slash >= 0:
        netloc, path = rest[:slash], rest[slash:]
    else:
        netloc, path = rest, ""
    if "@" not in netloc:
        return s
    userinfo, hostport = netloc.rsplit("@", 1)
    colon = userinfo.find(":")
    if colon < 0:
        return f"rtsp://{userinfo}@{hostport}{path}"
    user = userinfo[:colon]
    return f"rtsp://{user}:****@{hostport}{path}"


@dataclass
class GStreamerProbeMessage:
    level: str
    source: str
    text: str
    elapsed_ms: int


@dataclass
class GStreamerProbeResult:
    ok: bool
    rtsp_url_masked: str
    duration_sec: float
    elapsed_sec: float
    reached_playing: bool = False
    video_linked: bool = False
    video_codec: str | None = None
    pipeline_state: str = "NULL"
    buffer_count: int = 0
    error: str | None = None
    error_detail: str | None = None
    messages: list[GStreamerProbeMessage] = field(default_factory=list)
    gstreamer_available: bool = True
    import_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["messages"] = [asdict(m) for m in self.messages]
        return data


def _build_rtsp_debug_probe_pipeline(Gst, rtsp_url: str, *, on_video_linked):
    """
    rtspsrc -(pad-added, video RTP)-> queue -> depay/parse -> fakesink.
    Non-video RTP pads are drained to fakesink branches.
    """
    pipeline = Gst.Pipeline.new("rtsp_debug_probe")
    if pipeline is None:
        raise RuntimeError("GStreamer pipeline: failed to create pipeline")

    src = Gst.ElementFactory.make("rtspsrc", "camsrc")
    sink = Gst.ElementFactory.make("fakesink", "outsink")
    if not all([src, sink]):
        raise RuntimeError("GStreamer pipeline: missing required elements")

    pipeline.add(src)
    pipeline.add(sink)
    sink.set_property("sync", False)
    sink.set_property("async", False)

    link_state: dict[str, int | bool] = {"video_done": False, "drain_idx": 0}

    def _drain_unhandled_pad(pad, *, reason: str) -> None:
        if pad.is_linked():
            return

        idx = int(link_state["drain_idx"])
        link_state["drain_idx"] = idx + 1
        queue = Gst.ElementFactory.make("queue", f"drop_queue_{idx}")
        fakesink = Gst.ElementFactory.make("fakesink", f"drop_sink_{idx}")
        if not all([queue, fakesink]):
            return

        fakesink.set_property("sync", False)
        fakesink.set_property("async", False)
        pipeline.add(queue)
        pipeline.add(fakesink)
        if not queue.link(fakesink):
            for el in (queue, fakesink):
                el.set_state(Gst.State.NULL)
                pipeline.remove(el)
            return

        q_sink = queue.get_static_pad("sink")
        if q_sink is None:
            for el in (queue, fakesink):
                el.set_state(Gst.State.NULL)
                pipeline.remove(el)
            return

        if pad.link(q_sink) != Gst.PadLinkReturn.OK:
            for el in (queue, fakesink):
                el.set_state(Gst.State.NULL)
                pipeline.remove(el)
            return

        queue.sync_state_with_parent()
        fakesink.sync_state_with_parent()

    def _link_video_branch(pad, structure) -> bool:
        if bool(link_state["video_done"]):
            return True

        media = structure.get_string("media")
        if media != "video":
            return False

        encoding = (structure.get_string("encoding-name") or "").upper()
        if encoding == "HEVC":
            encoding = "H265"

        if encoding == "H264":
            depay_name, parse_name = "rtph264depay", "h264parse"
        elif encoding == "H265":
            depay_name, parse_name = "rtph265depay", "h265parse"
        else:
            return False

        queue = Gst.ElementFactory.make("queue", "video_queue")
        depay = Gst.ElementFactory.make(depay_name, "video_depay")
        parse_el = Gst.ElementFactory.make(parse_name, "video_parse")
        if not all([queue, depay, parse_el]):
            raise RuntimeError("GStreamer pipeline: failed to create depay/parse")

        pipeline.add(queue)
        pipeline.add(depay)
        pipeline.add(parse_el)

        q_sink = queue.get_static_pad("sink")
        if q_sink is None:
            raise RuntimeError("GStreamer pipeline: missing queue sink pad")

        if pad.link(q_sink) != Gst.PadLinkReturn.OK:
            for el in (queue, depay, parse_el):
                el.set_state(Gst.State.NULL)
                pipeline.remove(el)
            return False

        if not queue.link(depay):
            raise RuntimeError("GStreamer pipeline: failed link queue->depay")
        if not depay.link(parse_el):
            raise RuntimeError("GStreamer pipeline: failed link depay->parse")
        if not parse_el.link(sink):
            raise RuntimeError("GStreamer pipeline: failed link parse->sink")

        for el in (queue, depay, parse_el):
            el.sync_state_with_parent()

        link_state["video_done"] = True
        on_video_linked(encoding)
        return True

    def _attempt_link_rtsp_pad(pad) -> bool:
        caps = pad.get_current_caps() or pad.query_caps(None)
        if caps is None or caps.is_empty():
            return False

        structure = caps.get_structure(0)
        if structure.get_name() != "application/x-rtp":
            _drain_unhandled_pad(pad, reason=f"non-rtp:{structure.get_name()}")
            return True

        media = (structure.get_string("media") or "").lower()
        encoding = (structure.get_string("encoding-name") or "").upper()
        if media != "video":
            _drain_unhandled_pad(
                pad,
                reason=f"media={media or 'unknown'} encoding={encoding or 'unknown'}",
            )
            return True

        if bool(link_state["video_done"]):
            _drain_unhandled_pad(
                pad,
                reason=f"extra-video encoding={encoding or 'unknown'}",
            )
            return True

        if _link_video_branch(pad, structure):
            return True

        _drain_unhandled_pad(
            pad,
            reason=f"unsupported-video encoding={encoding or 'unknown'}",
        )
        return True

    def _on_caps_notify(pad, _pspec) -> None:
        if _attempt_link_rtsp_pad(pad):
            pad.disconnect_by_func(_on_caps_notify)

    def _on_rtsp_pad_added(_src, pad) -> None:
        if _attempt_link_rtsp_pad(pad):
            return

        cur = pad.get_current_caps()
        if cur is not None and not cur.is_empty():
            return

        pad.connect("notify::caps", _on_caps_notify)

    src.connect("pad-added", _on_rtsp_pad_added)
    src.set_property("location", rtsp_url)
    src.set_property("latency", RTSP_LATENCY_MS)
    src.set_property("protocols", RTSP_PROTOCOLS_TCP)
    return pipeline


def _message_level_name(Gst, message) -> str:
    t = message.type
    if t == Gst.MessageType.ERROR:
        return "ERROR"
    if t == Gst.MessageType.WARNING:
        return "WARNING"
    if t == Gst.MessageType.INFO:
        return "INFO"
    if t == Gst.MessageType.STATE_CHANGED:
        return "STATE"
    if t == Gst.MessageType.EOS:
        return "EOS"
    if t == Gst.MessageType.STREAM_START:
        return "STREAM_START"
    if t == Gst.MessageType.ASYNC_DONE:
        return "ASYNC_DONE"
    if t == Gst.MessageType.ELEMENT:
        return "ELEMENT"
    return t.value_nick.upper() if hasattr(t, "value_nick") else str(t)


def _format_message_text(Gst, message) -> str:
    t = message.type
    if t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        parts = [str(err).strip()]
        if debug:
            parts.append(debug.strip())
        return "\n".join(p for p in parts if p)
    if t == Gst.MessageType.WARNING:
        warn, debug = message.parse_warning()
        parts = [str(warn).strip()]
        if debug:
            parts.append(debug.strip())
        return "\n".join(p for p in parts if p)
    if t == Gst.MessageType.INFO:
        info, debug = message.parse_info()
        parts = [str(info).strip()]
        if debug:
            parts.append(debug.strip())
        return "\n".join(p for p in parts if p)
    if t == Gst.MessageType.STATE_CHANGED:
        old, new, pending = message.parse_state_changed()
        return f"{old.value_nick} -> {new.value_nick}" + (
            f" (pending {pending.value_nick})"
            if pending != Gst.State.VOID_PENDING
            else ""
        )
    if t == Gst.MessageType.ELEMENT:
        s = message.get_structure()
        if s is not None:
            return s.to_string()
    return ""


def _pipeline_state_name(Gst, pipeline) -> str:
    if pipeline is None:
        return "NULL"
    _ret, state, _pending = pipeline.get_state(0)
    return state.value_nick.upper()


def probe_rtsp_gstreamer(
    rtsp_url: str,
    *,
    duration_sec: float = DEFAULT_PROBE_DURATION_SEC,
    startup_timeout_sec: float = STARTUP_TIMEOUT_SEC,
) -> GStreamerProbeResult:
    """
    Run a short GStreamer probe against ``rtsp_url`` and return structured diagnostics.
    """
    sanitized = sanitize_rtsp_url((rtsp_url or "").strip())
    masked = mask_rtsp_credentials(sanitized)
    duration = max(
        MIN_PROBE_DURATION_SEC, min(float(duration_sec), MAX_PROBE_DURATION_SEC)
    )

    result = GStreamerProbeResult(
        ok=False,
        rtsp_url_masked=masked,
        duration_sec=duration,
        elapsed_sec=0.0,
    )

    if not sanitized:
        result.error = "RTSP URL is required."
        return result

    try:
        Gst, GLib = _gi()
    except ImportError as exc:
        result.gstreamer_available = False
        result.import_error = str(exc)
        result.error = "GStreamer / PyGObject is not available in this process."
        return result

    started_at = time.monotonic()
    messages: list[GStreamerProbeMessage] = []
    buffer_count = {"n": 0}
    state = {
        "reached_playing": False,
        "video_linked": False,
        "video_codec": None,
        "failure_reason": None,
        "failure_detail": None,
        "stopped": False,
        "pipeline": None,
    }

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started_at) * 1000)

    def _append_message(level: str, source: str, text: str) -> None:
        if not text:
            return
        messages.append(
            GStreamerProbeMessage(
                level=level,
                source=source,
                text=text,
                elapsed_ms=_elapsed_ms(),
            )
        )

    def _on_video_linked(codec: str) -> None:
        state["video_linked"] = True
        state["video_codec"] = codec
        _append_message("INFO", "probe", f"Video RTP branch linked (codec={codec})")

    loop = GLib.MainLoop()

    def _stop_pipeline(*, reason: str | None = None, detail: str | None = None) -> None:
        if state["stopped"]:
            return
        state["stopped"] = True
        if reason:
            state["failure_reason"] = reason
        if detail:
            state["failure_detail"] = detail
        pipeline = state["pipeline"]
        if pipeline is not None:
            try:
                bus = pipeline.get_bus()
                bus.remove_signal_watch()
            except Exception:
                pass
            pipeline.set_state(Gst.State.NULL)
            state["pipeline"] = None
        loop.quit()

    def _on_message(_bus, message):
        src = message.src
        source_name = src.get_name() if src is not None else "pipeline"
        level = _message_level_name(Gst, message)
        text = _format_message_text(Gst, message)
        _append_message(level, source_name, text)

        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            state["failure_reason"] = "gstreamer_error"
            state["failure_detail"] = _format_gstreamer_error(err, debug)
            _stop_pipeline()
        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src == state["pipeline"]:
                _old, new, _pending = message.parse_state_changed()
                if new == Gst.State.PLAYING:
                    state["reached_playing"] = True

    def _on_startup_timeout() -> bool:
        if state["reached_playing"]:
            return False
        state["failure_reason"] = "startup_timeout"
        state["failure_detail"] = (
            f"Pipeline did not reach PLAYING within {startup_timeout_sec:g}s"
        )
        _stop_pipeline()
        return False

    def _on_duration_timeout() -> bool:
        _stop_pipeline()
        return False

    try:
        pipeline = _build_rtsp_debug_probe_pipeline(
            Gst, sanitized, on_video_linked=_on_video_linked
        )
    except Exception as exc:
        logger.exception("GStreamer probe: pipeline build failed")
        result.error = "pipeline_build_failed"
        result.error_detail = str(exc)
        result.elapsed_sec = time.monotonic() - started_at
        result.messages = messages
        return result

    state["pipeline"] = pipeline
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", _on_message)

    sink = pipeline.get_by_name("outsink")
    if sink is not None:
        pad = sink.get_static_pad("sink")
        if pad is not None:

            def _on_buffer(_pad, _info):
                buffer_count["n"] += 1
                return Gst.PadProbeReturn.OK

            pad.add_probe(Gst.PadProbeType.BUFFER, _on_buffer)

    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        result.error = "startup_failed"
        result.error_detail = "GStreamer failed to set pipeline to PLAYING."
        result.pipeline_state = _pipeline_state_name(Gst, pipeline)
        pipeline.set_state(Gst.State.NULL)
        result.elapsed_sec = time.monotonic() - started_at
        result.messages = messages
        return result

    GLib.timeout_add_seconds(int(startup_timeout_sec), _on_startup_timeout)
    GLib.timeout_add_seconds(int(duration), _on_duration_timeout)

    try:
        loop.run()
    except Exception as exc:
        logger.exception("GStreamer probe: main loop failed")
        state["failure_reason"] = "loop_error"
        state["failure_detail"] = str(exc)
    finally:
        if state["pipeline"] is not None:
            result.pipeline_state = _pipeline_state_name(Gst, state["pipeline"])
            state["pipeline"].set_state(Gst.State.NULL)
            state["pipeline"] = None

    result.elapsed_sec = round(time.monotonic() - started_at, 2)
    result.reached_playing = bool(state["reached_playing"])
    result.video_linked = bool(state["video_linked"])
    result.video_codec = state["video_codec"]
    result.buffer_count = int(buffer_count["n"])
    if not result.pipeline_state or result.pipeline_state == "NULL":
        result.pipeline_state = "NULL"
    result.messages = messages
    result.error = state["failure_reason"]
    result.error_detail = state["failure_detail"]
    result.ok = (
        result.reached_playing
        and result.video_linked
        and result.buffer_count > 0
        and not result.error
    )
    return result
