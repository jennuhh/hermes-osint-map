"""Ship positions from AIS: the Finnish Digitraffic open feed (keyless, Baltic Sea) plus an
optional global aisstream.io WebSocket collector behind a key.

AIS is a broadcast protocol: vessels shout position, course and status every few seconds, coast
stations collect it, and aggregators republish it. Digitraffic (Finland's Transport Infrastructure
Agency, CC BY 4.0) republishes everything their stations hear as two plain HTTP lists — positions
and vessel metadata — which makes it the honest, no-key way to run the whole pipeline. aisstream.io
adds worldwide coverage behind a free key, as a push stream: a background collector thread holds
the latest report per MMSI, and the layer reads that store like any other part.

Nothing identifies people: an MMSI names a vessel, not a person, and cards show only what the
vessel itself broadcasts (name, type, destination, speed, course).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

from . import http
from .http import UpstreamError

DIGITRAFFIC_LOCATIONS = "https://meri.digitraffic.fi/api/ais/v1/locations"
DIGITRAFFIC_VESSELS = "https://meri.digitraffic.fi/api/ais/v1/vessels"
AISSTREAM_WS = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_ENV = "AISSTREAM_API_KEY"
OPENWATERS_WS = "wss://ais.openwaters.io/v1/stream"
# Where the keyless regional stream points: minLat, minLon, maxLat, maxLon. The Strait of
# Hormuz is the standing OSINT question (tanker traffic, the UKMTO beat); 4x4 deg fits the
# anonymous tier's 100 sq-degree area cap with room to spare. Override with SHIPS_WATCH_BOX.
DEFAULT_WATCH_BOX = (24.0, 54.5, 28.0, 58.5)
WATCH_BOX_ENV = "SHIPS_WATCH_BOX"
DIGITRAFFIC_ATTRIBUTION = "Finnish Transport Infrastructure Agency (Digitraffic, CC BY 4.0)"

RETAIN_S = 6 * 3600  # keep the last report per MMSI for six hours (sparse regions accumulate)
MAX_SOG_KTS = 40.0  # AIS encodes "unavailable" as 102.3; real ships rarely exceed 30

# AIS ship-type codes (the type field's high digit says the family; low digit refines it).
SHIP_TYPES = {
    30: "fishing", 31: "towing", 32: "towing (large)", 33: "dredging", 34: "diving",
    35: "military", 36: "sailing", 37: "pleasure craft", 50: "pilot", 51: "search and rescue",
    52: "tug", 53: "port tender", 54: "anti-pollution", 55: "law enforcement", 58: "medical",
    60: "passenger", 70: "cargo", 71: "cargo (hazard A)", 72: "cargo (hazard B)",
    73: "cargo (hazard C)", 74: "cargo (hazard D)", 80: "tanker", 81: "tanker (hazard A)",
    82: "tanker (hazard B)", 83: "tanker (hazard C)", 84: "tanker (hazard D)", 90: "other",
}

NAV_STATUS = {
    0: "under way (engine)", 1: "at anchor", 2: "not under command", 3: "restricted manoeuvre",
    4: "constrained by draught", 5: "moored", 6: "aground", 7: "fishing", 8: "under way (sail)",
    15: "undefined",
}

# Maritime Identification Digits: the first three MMSI digits name the flag state. This is a
# deliberately partial list of the flags that carry most of the world's tonnage; an MMSI whose
# MID is absent simply gets no country, rather than a guess.
MIDS = {
    201: "AL", 205: "BE", 209: "CY", 210: "CY", 211: "DE", 212: "CY", 215: "MT", 219: "DK",
    220: "DK", 224: "ES", 226: "FR", 227: "FR", 228: "FR", 229: "MT", 230: "FI", 231: "FO",
    232: "GB", 233: "GB", 234: "GB", 235: "GB", 236: "GI", 237: "GR", 238: "HR", 239: "GR",
    240: "GR", 241: "GR", 242: "MA", 244: "NL", 245: "NL", 246: "NL", 247: "IT", 248: "MT",
    249: "MT", 253: "LU", 255: "PT", 256: "MT", 257: "NO", 258: "NO", 259: "NO", 261: "PL",
    263: "PT", 264: "RO", 265: "SE", 266: "SE", 267: "SK", 269: "CH", 270: "CZ", 271: "TR",
    272: "UA", 273: "RU", 275: "LV", 276: "EE", 277: "LT", 278: "BG", 279: "SI",
    303: "US", 305: "AG", 306: "CW", 308: "BS", 311: "BS", 312: "BZ", 314: "BB", 316: "CA",
    319: "KY", 338: "US", 341: "JM", 345: "MX", 351: "PA", 352: "PA", 353: "PA", 354: "PA",
    355: "PA", 356: "PA", 357: "PA", 370: "PA", 371: "PA", 372: "PA", 373: "PA", 374: "PA",
    375: "PA", 376: "PA", 377: "PA", 378: "PA",
    # Gulf / Central Asia (ITU Appendix 43; verified against ITU, Wikipedia and two MID tables).
    # 401/403 were mis-filed before 2026-11-08 (Afghanistan/Saudi, not Canada/Greenland).
    401: "AF", 403: "SA", 405: "BD", 408: "BH", 412: "CN", 413: "CN",
    414: "CN", 416: "TW", 417: "LK", 419: "IN", 422: "IR", 423: "AZ", 425: "IQ", 428: "IL",
    431: "JP", 432: "JP", 433: "JP", 434: "TM", 436: "KZ", 437: "UZ", 438: "JO", 440: "KR",
    441: "KR", 443: "PS", 445: "KP", 447: "KW", 450: "LB", 451: "KG", 453: "MO", 455: "MV",
    457: "MN", 459: "NP", 461: "OM", 463: "PK", 466: "QA", 468: "SY", 470: "AE", 472: "TJ",
    473: "YE", 475: "YE", 477: "HK", 478: "HK", 501: "MH", 503: "AU", 508: "CK", 510: "FM", 511: "PW",
    512: "NZ", 514: "TO", 515: "TO", 518: "WS", 525: "VU", 533: "MY", 536: "SG", 537: "SG",
    538: "MH", 540: "SB", 542: "FJ", 548: "PH", 553: "TH", 555: "VN", 557: "VN",
    563: "SG", 564: "SG", 565: "SG", 566: "SG", 567: "TH", 574: "VN", 577: "HK", 579: "HK",
    616: "ZW", 621: "GM", 622: "LR", 624: "LR", 625: "LR", 626: "LR", 627: "LR", 629: "NG",
    630: "LR", 633: "CM", 636: "LR", 637: "LR", 642: "LY", 645: "MU", 649: "SC", 657: "NG",
    664: "CM", 677: "TZ",
}

MILITARY_SEVERITY = 0.9


def ship_type(raw: Any) -> str | None:
    code = raw if isinstance(raw, int) else None
    if code is None:
        return None
    if code in SHIP_TYPES:
        return SHIP_TYPES[code]
    family = code // 10 * 10
    return SHIP_TYPES.get(family)  # e.g. 79 → cargo family is not exact; only exact families map


def flag(mmsi: Any) -> str | None:
    if not isinstance(mmsi, int) or not 100000000 <= mmsi <= 999999999:
        return None
    return MIDS.get(mmsi // 1000000)


def severity_for(kind: str | None) -> float:
    if kind is None:
        return 0.3
    if kind == "military":
        return MILITARY_SEVERITY
    if kind.startswith("tanker") or kind == "cargo":
        return 0.55
    return 0.35


# --- Parsing (pure; no I/O here so tests run on recorded fixtures) ---------------------------------


def _clip(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if low <= value <= high else None


def parse_digitraffic(locations: Any, vessels: Any) -> list[dict]:
    """Digitraffic ``locations`` + ``vessels`` lists → ship items, keyed by MMSI."""
    if not isinstance(locations, dict) or not isinstance(locations.get("features"), list):
        return []
    static: dict[int, dict] = {}
    if isinstance(vessels, list):
        for entry in vessels:
            if isinstance(entry, dict) and isinstance(entry.get("mmsi"), int):
                static[entry["mmsi"]] = entry
    out = []
    for feature in locations["features"]:
        if not isinstance(feature, dict):
            continue
        mmsi = feature.get("mmsi")
        raw_geometry = feature.get("geometry")
        geometry = raw_geometry if isinstance(raw_geometry, dict) else {}
        coords = geometry.get("coordinates")
        raw_props = feature.get("properties")
        props = raw_props if isinstance(raw_props, dict) else {}
        if not isinstance(mmsi, int) or not isinstance(coords, list) or len(coords) != 2:
            continue
        lon, lat = coords[0], coords[1]
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or (
                lat == 0 and lon == 0):
            continue
        out.append(_ship_item(mmsi, lat, lon, props, static.get(mmsi) or {},
                              props.get("timestampExternal")))
    return out


def _ship_item(mmsi: int, lat: float, lon: float, pos: dict, static: dict,
               timestamp_ms: Any) -> dict:
    from .parsers import item  # local import: parsers has no dependency on this module

    sog = _clip(pos.get("sog"), 0, MAX_SOG_KTS)
    heading = pos.get("heading")
    heading_valid = _clip(heading, 0, 359) if heading not in (None, 511) else None
    course = _clip(pos.get("cog"), 0, 360)
    kind = ship_type(static.get("shipType"))
    raw_name = static.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else None
    raw_destination = static.get("destination")
    destination = raw_destination if isinstance(raw_destination, str) else None
    nav = pos.get("navStat")
    status = NAV_STATUS.get(nav) if isinstance(nav, int) else None
    draught = _clip(static.get("draught"), 0, 255)
    rows = [("MMSI", str(mmsi))]
    if status:
        rows.append(("Status", status))
    if destination and destination.strip():
        rows.append(("Destination", destination.strip()))
    if isinstance(static.get("imo"), int) and static["imo"]:
        rows.append(("IMO", str(static["imo"])))
    if draught is not None and static.get("draught") != 0:
        rows.append(("Draught", f"{draught / 10:.1f} m"))
    stamp = timestamp_ms if isinstance(timestamp_ms, (int, float)) else None
    return item(
        "ships", mmsi, kind or "vessel", lat, lon,
        name or f"MMSI {mmsi}",
        subtitle=" · ".join(part for part in (kind, status) if part),
        severity=severity_for(kind),
        time=int(stamp) if stamp and 0 < stamp < 8.64e15 else None,
        country=flag(mmsi),
        heading=heading_valid if heading_valid is not None else course,
        speed_kts=sog,
        rows=rows,
    )


def parse_aisstream(message: Any, pos_store: dict[int, dict], static_store: dict[int, dict]) -> bool:
    """One decoded aisstream.io JSON message → into the collector stores. Returns True when the
    message was a position or static report this plugin understands; anything else is ignored."""
    if not isinstance(message, dict):
        return False
    message_type = message.get("MessageTypeId")
    raw_meta = message.get("MetaData")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    mmsi = meta.get("MMSI")
    if not isinstance(mmsi, int):
        return False
    now = time.time()
    if message_type in (1, 2, 3):  # positional reports
        report = message.get("Message")
        report = report.get("PositionReport") if isinstance(report, dict) else {}
        if not isinstance(report, dict):
            return False
        # aisstream.io carries the fix in MetaData ("latitude"/"longitude"); some deployments
        # also repeat it in the PositionReport itself. Accept either, trust neither blindly.
        lat, lon = meta.get("latitude"), meta.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            lat, lon = report.get("Latitude"), report.get("Longitude")
        pos_store[mmsi] = {
            "lat": lat, "lon": lon,
            "sog": report.get("Sog"), "cog": report.get("Cog"),
            "heading": report.get("TrueHeading"), "navStat": report.get("NavigationalStatus"),
            "time": _aisstream_time(meta.get("time_utc"), now), "seen": now,
        }
        raw_name = meta.get("ShipName")  # position reports repeat the name; keep it as a fallback
        if isinstance(raw_name, str) and raw_name.strip():
            known = static_store.get(mmsi)
            if known is None:
                static_store[mmsi] = {"name": raw_name.strip(), "seen": now}
            elif not known.get("name"):
                known["name"] = raw_name.strip()
        return True
    if message_type == 5:  # ship static and voyage data
        body = message.get("Message")
        body = body.get("ShipStaticAndVoyageData") if isinstance(body, dict) else {}
        if not isinstance(body, dict):
            return False
        static_store[mmsi] = {
            "name": body.get("Name"), "shipType": body.get("Type"),
            "destination": body.get("Destination"), "imo": body.get("IMO"),
            "callSign": body.get("CallSign"), "seen": now,
        }
        return True
    return False


def watch_box() -> tuple[float, float, float, float]:
    """The regional stream's box, from SHIPS_WATCH_BOX ("minLat,minLon,maxLat,maxLon") or Hormuz."""
    raw = os.environ.get(WATCH_BOX_ENV)  # a bounding box is not a credential: plain env is fine
    if isinstance(raw, str) and raw.count(",") == 3:
        try:
            lat0, lon0, lat1, lon1 = (float(part) for part in raw.split(","))
            if -90 <= lat0 < lat1 <= 90 and -180 <= lon0 < lon1 <= 180:
                return (lat0, lon0, lat1, lon1)
        except ValueError:
            pass
    return DEFAULT_WATCH_BOX


def parse_openwaters(event: Any, pos_store: dict, static_store: dict) -> bool:
    """One Open Waters AIS /v1 event frame into the collector stores. Returns True if used.

    Shape (their native dialect, not aisstream's): {"type": "event", "mmsi": ..., "time": ISO,
    "msg_type": "PositionReport" | "ShipStaticData" | ..., "lat": ..., "lon": ...,
    "message": {decoded AIS fields}}. The decoded body keeps aisstream-ish key names, so the
    stores end up identical and collector_items() serves both feeds unchanged."""
    if not isinstance(event, dict) or event.get("type") != "event":
        return False
    mmsi = event.get("mmsi")
    if not isinstance(mmsi, int) or mmsi <= 0:
        return False
    body = event.get("message")
    body = body if isinstance(body, dict) else {}
    now = time.time()
    msg_type = str(event.get("msg_type") or "")
    if msg_type == "PositionReport":
        lat, lon = event.get("lat"), event.get("lon")
        pos_store[mmsi] = {
            "lat": lat, "lon": lon,
            "sog": body.get("Sog"), "cog": body.get("Cog"),
            "heading": body.get("TrueHeading"), "navStat": body.get("NavigationalStatus"),
            "time": _aisstream_time(event.get("time"), now), "seen": now,
        }
        return True
    if "Static" in msg_type or "Voyage" in msg_type:
        name = body.get("Name") or body.get("name")
        static_store.setdefault(mmsi, {"seen": now})
        known = static_store[mmsi]
        if isinstance(name, str) and name.strip() and not known.get("name"):
            known["name"] = name.strip()
        for src, dst in (("Type", "shipType"), ("Destination", "destination"), ("IMO", "imo"),
                         ("CallSign", "callSign"), ("Draught", "draught")):
            value = body.get(src)
            if value is not None and not known.get(dst):
                known[dst] = value
        known["seen"] = now
        return True
    return False


def _aisstream_time(raw: Any, fallback: float) -> float:
    if isinstance(raw, str):
        try:
            from datetime import datetime, timezone
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() if raw else fallback
        except ValueError:
            return fallback
    return fallback


def collector_items(pos_store: dict[int, dict], static_store: dict[int, dict]) -> list[dict]:
    """The collector's stores → ship items (the same shape the Digitraffic feed makes)."""
    out = []
    cutoff = time.time() - RETAIN_S
    for mmsi, pos in list(pos_store.items()):
        seen = pos.get("seen")
        if not isinstance(seen, (int, float)) or seen < cutoff:
            continue
        lat, lon = pos.get("lat"), pos.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        stamp = pos.get("time")
        stamp_ms = int(stamp * 1000) if isinstance(stamp, (int, float)) else None
        out.append(_ship_item(mmsi, lat, lon, pos, static_store.get(mmsi) or {}, stamp_ms))
    return out


# --- The aisstream.io collector thread --------------------------------------------------------------


class AisstreamCollector:
    """One WebSocket, opened lazily when a key is configured, holding the latest report per MMSI.

    The thread reconnects with a backoff and never raises: a dead collector just leaves the store
    stale, and the layer reports it the way it reports any other failed part."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._positions: dict[int, dict] = {}
        self._static: dict[int, dict] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle | connecting | live | waiting | stopped
        self._detail = ""

    def start(self, key: str | None) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._state, self._detail = "connecting", ""
            self._thread = threading.Thread(target=self._run, args=(key,), daemon=True,
                                            name="osint-aisstream")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def state(self) -> dict:
        with self._lock:
            return {"state": self._state, "detail": self._detail,
                    "positions": len(self._positions), "static": len(self._static)}

    def items(self) -> list[dict]:
        with self._lock:
            return collector_items(self._positions, self._static)

    def _run(self, key: str | None) -> None:
        import asyncio
        import json as _json

        async def once_aisstream() -> None:
            import websockets

            async with websockets.connect(AISSTREAM_WS, open_timeout=20,
                                          ping_interval=25, ping_timeout=20) as ws:
                await ws.send(_json.dumps({
                    "APIKey": key,
                    "BoundingBoxes": [[[-90, -180], [90, 180]]],
                    "FilterMessageTypes": ["PositionReport", "ShipStaticAndVoyageData"],
                }))
                with self._lock:
                    self._state, self._detail = "live", ""
                while not self._stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=75)
                    if not raw:
                        continue
                    try:
                        message = _json.loads(raw)
                    except ValueError:
                        continue
                    with self._lock:
                        parse_aisstream(message, self._positions, self._static)
                        self._prune()

        async def once_openwaters() -> None:
            import websockets

            box = watch_box()
            async with websockets.connect(OPENWATERS_WS, open_timeout=20,
                                          ping_interval=25, ping_timeout=20) as ws:
                # Their native dialect: bbox = [minLat, minLon, maxLat, maxLon]; snapshot replays
                # the last known state of every vessel already in the box, so the map is never empty.
                await ws.send(_json.dumps({"type": "subscribe", "bbox": [list(box)], "snapshot": True}))
                with self._lock:
                    self._state, self._detail = "live", ""
                while not self._stop.is_set():
                    raw = await asyncio.wait_for(ws.recv(), timeout=75)
                    if not raw:
                        continue
                    try:
                        message = _json.loads(raw)
                    except ValueError:
                        continue
                    with self._lock:
                        parse_openwaters(message, self._positions, self._static)
                        self._prune()

        async def collect() -> None:
            backoff = 2.0
            ais_next_ok = 0.0  # monotonic time before which aisstream.io may not be re-tried
            while not self._stop.is_set():
                use_ais = bool(key) and time.monotonic() >= ais_next_ok
                feed = "aisstream.io" if use_ais else "openwaters"
                try:
                    if use_ais:
                        await once_aisstream()
                    else:
                        await once_openwaters()
                    backoff = 2.0
                except Exception as exc:  # never raise out of a collector thread
                    if use_ais:
                        # aisstream has a documented habit of closing everything with no reason
                        # (1006). One quick attempt, then an hour on Open Waters, which answers.
                        ais_next_ok = time.monotonic() + 3600.0
                        with self._lock:
                            self._state, self._detail = "connecting", (
                                f"aisstream.io: {describe_collect(exc)} — falling back to Open Waters.")
                        continue  # straight to the working feed, no backoff sleep
                    with self._lock:
                        self._state, self._detail = "waiting", f"openwaters: {describe_collect(exc)}"
                    if self._stop.wait(backoff):
                        break
                    backoff = min(backoff * 2, 300.0)

        asyncio.run(collect())
        with self._lock:
            self._state = "stopped"

    def _prune(self) -> None:
        cutoff = time.time() - RETAIN_S
        for store in (self._positions, self._static):
            for mmsi in [m for m, v in store.items() if v.get("seen", 0) < cutoff]:
                del store[mmsi]


def describe_collect(exc: BaseException) -> str:
    name = type(exc).__name__
    if "Timeout" in name or isinstance(exc, TimeoutError):
        return "the AIS stream took too long to answer."
    if "InvalidHandshake" in name or "ConnectionClosed" in name or isinstance(exc, ConnectionError):
        reason = getattr(exc, "rcvd", None)
        note = f" ({reason.reason.decode(errors='replace')[:80]})" if reason and getattr(reason, "reason", None) else ""
        return f"the AIS stream closed the connection{note}; retrying."
    return f"the AIS collector stopped on {name}; retrying."


_COLLECTOR = AisstreamCollector()


def collector() -> AisstreamCollector:
    return _COLLECTOR


def aisstream_key() -> str | None:
    """The optional aisstream.io key, read only through Hermes's secret scope (the Twelve Data
    pattern). Outside Hermes, or with no scope in this process, it behaves as if unset."""
    try:
        from agent.secret_scope import get_secret
        value = get_secret(AISSTREAM_ENV)
    except Exception:
        value = None
    return value.strip() if isinstance(value, str) and value.strip() else None


def digitraffic_load() -> Callable[[], dict]:
    def load() -> dict:
        locations = http.get_json(DIGITRAFFIC_LOCATIONS, source="Digitraffic", timeout=20.0,
                                  headers={"Accept-Encoding": "gzip"})
        vessels = http.get_json(DIGITRAFFIC_VESSELS, source="Digitraffic", timeout=20.0,
                                headers={"Accept-Encoding": "gzip"})
        found = parse_digitraffic(locations, vessels)
        if not found:
            raise UpstreamError(502, "Digitraffic answered but listed no vessels.")
        return {"items": found}
    return load


def stream_load() -> Callable[[], dict]:
    """The collector part of the ships layer: aisstream.io worldwide when a key is set,
    otherwise the keyless Open Waters regional stream (default box: Strait of Hormuz)."""
    def load() -> dict:
        key = aisstream_key()
        _COLLECTOR.start(key)
        # First fetch after a cold start: the collector has to connect (and, with a key set,
        # survive one fast aisstream.io attempt before falling back). Poll up to ~15 s instead
        # of one blind 3 s sleep so the first answer is usually green, not an UpstreamError.
        deadline = time.time() + 15.0
        found = _COLLECTOR.items()
        while not found and time.time() < deadline:
            state = _COLLECTOR.state()
            if state["state"] in ("idle", "stopped"):
                break
            time.sleep(1.5)
            found = _COLLECTOR.items()
        state = _COLLECTOR.state()
        if not found:
            raise UpstreamError(502, f"ships collector is {state['state']}"
                                     + (f": {state['detail']}" if state["detail"] else ""))
        return {"items": found}
    return load
