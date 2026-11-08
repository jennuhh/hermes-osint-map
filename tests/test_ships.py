"""Ships: parsing the Digitraffic AIS feeds, flag lookup, and the stream collector stores."""

import time

import pytest

from osintmap import layers, ships

LOCATIONS = {"features": [
    # A named tanker with valid heading, speed and metadata (MID 276 = Estonia).
    {"mmsi": 276417000, "type": "Feature",
     "geometry": {"type": "Point", "coordinates": [24.9, 59.9]},
     "properties": {"mmsi": 276417000, "sog": 12.5, "cog": 87.0, "navStat": 0, "heading": 88,
                    "timestampExternal": 1794072953305}},
    # A vessel whose heading is the AIS "unavailable" value: course over ground is used instead.
    {"mmsi": 372002000, "type": "Feature",
     "geometry": {"type": "Point", "coordinates": [21.3, 58.9]},
     "properties": {"mmsi": 372002000, "sog": 14.9, "cog": 214.0, "heading": 511,
                    "timestampExternal": 1794072953300}},
    # No position fix (0, 0 is "no fix" in most feeds) and junk shapes are dropped.
    {"mmsi": 111111111, "type": "Feature",
     "geometry": {"type": "Point", "coordinates": [0, 0]},
     "properties": {"mmsi": 111111111, "sog": 0, "cog": 0, "heading": 511,
                    "timestampExternal": 1794072953300}},
    {"mmsi": 222222222, "type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
     "properties": {"mmsi": 222222222, "sog": 102.3, "cog": None, "heading": 511}},
    "junk",
    {"mmsi": 333333333, "type": "Feature",
     "geometry": {"type": "Point", "coordinates": [25.0, 60.0]}, "properties": {}},
]}

VESSELS = [
    {"mmsi": 276417000, "name": "TEST TANKER", "shipType": 80, "destination": "FI HEL",
     "callSign": "ESAJ", "imo": 9183790, "draught": 69},
    {"mmsi": 372002000, "name": "  ", "shipType": 70, "destination": "", "draught": 0},
    {"mmsi": 999, "name": "NO POSITION"},  # in the metadata list, absent from positions
]


def test_parse_digitraffic_merges_positions_and_metadata():
    items = ships.parse_digitraffic(LOCATIONS, VESSELS)
    assert len(items) == 4  # the no-fix fix, the junk string and the bad mmsi are dropped

    tanker = next(i for i in items if i["id"] == "ships:276417000")
    assert tanker["title"] == "TEST TANKER"
    assert tanker["kind"] == "tanker"
    assert tanker["country"] == "EE"  # MID 276 = Estonia
    assert tanker["heading"] == 88.0  # valid true heading wins over course
    assert tanker["speed_kts"] == 12.5
    assert tanker["time"] == 1794072953305
    assert ["Destination", "FI HEL"] in tanker["props"]
    assert ["IMO", "9183790"] in tanker["props"]
    assert ["Draught", "6.9 m"] in tanker["props"]
    assert tanker["severity"] > 0.5  # tankers rank above the default

    unnamed = next(i for i in items if i["id"] == "ships:372002000")
    assert unnamed["title"] == "MMSI 372002000"
    assert unnamed["heading"] == 214.0  # heading 511 = unavailable → course over ground
    assert ("IMO", "9183790") not in unnamed["props"]

    clipped = next(i for i in items if i["id"] == "ships:222222222")
    assert clipped["speed_kts"] is None and clipped["country"] is None  # sog 102.3 = unavailable

    bare = next(i for i in items if i["id"] == "ships:333333333")
    assert bare["kind"] == "vessel"  # no metadata at all: neutral kind, no crash


def test_parse_digitraffic_rejects_wrong_shapes():
    assert ships.parse_digitraffic(None, VESSELS) == []
    assert ships.parse_digitraffic({}, []) == []
    assert ships.parse_digitraffic({"features": None}, []) == []


def test_flag_uses_the_mmsi_prefix_and_admits_ignorance():
    assert ships.flag(351234000) == "PA"  # Panama range
    assert ships.flag(276417000) == "EE"
    assert ships.flag(273417000) == "RU"  # Russia, adjacent range: no guessing across MIDs
    assert ships.flag(123) is None  # too short to be an MMSI
    assert ships.flag(None) is None


def test_military_ships_rank_first():
    assert ships.severity_for("military") > ships.severity_for("tanker")
    assert ships.ship_type(80) == "tanker" and ships.ship_type(70) == "cargo"
    assert ships.ship_type(None) is None


def test_aisstream_messages_fill_the_collector_stores():
    pos, static = {}, {}
    position = {"MessageTypeId": 1, "MetaData": {"MMSI": 351234000, "latitude": 26.5,
                                                 "longitude": 56.2, "time_utc": "2026-11-07T20:00:00+00:00"},
                "Message": {"PositionReport": {"Sog": 10.0, "Cog": 270.0, "TrueHeading": 269,
                                               "NavigationalStatus": 0}}}
    voyage = {"MessageTypeId": 5, "MetaData": {"MMSI": 351234000},
              "Message": {"ShipStaticAndVoyageData": {"Name": "HORMUZ RUNNER", "Type": 80,
                                                      "Destination": "JO AQJ", "IMO": 1234567}}}
    assert ships.parse_aisstream(position, pos, static) is True
    assert ships.parse_aisstream(voyage, pos, static) is True
    assert ships.parse_aisstream({"MessageTypeId": 99}, pos, static) is False
    assert ships.parse_aisstream({"MessageTypeId": 1, "MetaData": {}}, pos, static) is False

    items = ships.collector_items(pos, static)
    assert len(items) == 1
    card = items[0]
    assert card["title"] == "HORMUZ RUNNER"
    assert card["kind"] == "tanker"
    assert card["country"] == "PA"
    assert card["lat"] == 26.5 and card["lon"] == 56.2
    assert card["heading"] == 269.0


def test_collector_drops_stale_positions():
    pos = {356: {"lat": 1.0, "lon": 2.0, "sog": 5, "cog": 90, "heading": 511, "navStat": 0,
                 "time": time.time(), "seen": time.time() - ships.RETAIN_S - 10}}
    assert ships.collector_items(pos, {}) == []


def test_openwaters_events_fill_the_same_stores():
    pos, static = {}, {}
    position = {"type": "event", "mmsi": 470721000, "time": "2026-11-08T00:40:57Z",
                "msg_type": "PositionReport", "lat": 24.387, "lon": 54.501, "source": "aishub",
                "message": {"Sog": 9.5, "Cog": 122.0, "TrueHeading": 511, "NavigationalStatus": 0}}
    static_event = {"type": "event", "mmsi": 470721000, "msg_type": "ShipStaticData",
                    "message": {"Name": "AL SHUWAYHAT", "Type": 70, "Destination": "AE JEA"}}
    assert ships.parse_openwaters(position, pos, static) is True
    assert ships.parse_openwaters(static_event, pos, static) is True
    assert ships.parse_openwaters({"type": "welcome"}, pos, static) is False
    assert ships.parse_openwaters({"type": "event"}, pos, static) is False  # no mmsi

    items = ships.collector_items(pos, static)
    assert len(items) == 1
    card = items[0]
    assert card["title"] == "AL SHUWAYHAT" and card["kind"] == "cargo" and card["country"] == "AE"
    assert card["lat"] == 24.387 and card["lon"] == 54.501
    assert card["heading"] == 122.0  # 511 = unavailable → course over ground
    assert ["Destination", "AE JEA"] in card["props"]


def test_watch_box_defaults_to_hormuz_and_validates_overrides(monkeypatch):
    assert ships.watch_box() == ships.DEFAULT_WATCH_BOX
    monkeypatch.setenv(ships.WATCH_BOX_ENV, "55.0,25.0,57.0,27.0")
    assert ships.watch_box() == (55.0, 25.0, 57.0, 27.0)  # note: read through the secret scope's env fallback
    monkeypatch.setenv(ships.WATCH_BOX_ENV, "not,a,box")
    assert ships.watch_box() == ships.DEFAULT_WATCH_BOX
    monkeypatch.setenv(ships.WATCH_BOX_ENV, "40.0,50.0,30.0,60.0")  # inverted: refuse
    assert ships.watch_box() == ships.DEFAULT_WATCH_BOX


def test_ships_layer_fetches_end_to_end(monkeypatch):
    monkeypatch.setattr(ships.http, "get_json", lambda url, **kw: LOCATIONS if "locations" in url else VESSELS)
    monkeypatch.setattr(ships, "stream_load", lambda: lambda: {"items": []})  # keep the ws collector out of it
    monkeypatch.setattr(layers, "ships", ships)
    monkeypatch.setattr(layers, "_cache", layers.SnapshotCache(size=8))
    result = layers.fetch("ships")
    assert result["status"] == "ok"
    assert result["count"] == 4
    assert result["items"][0]["layer"] == "ships"
    assert layers.fetch("ships")["count"] == 4  # second call is served from the snapshot cache


def test_ships_layer_reports_upstream_failure(monkeypatch):
    from osintmap.http import UpstreamError

    def boom(url, **kw):
        raise UpstreamError(503, "Could not reach Digitraffic.")

    monkeypatch.setattr(ships.http, "get_json", boom)
    monkeypatch.setattr(layers, "ships", ships)
    monkeypatch.setattr(layers, "_cache", layers.SnapshotCache(size=8))
    layers.reset()
    result = layers.fetch("ships")
    assert result["status"] == "error"
    assert "Digitraffic" in (result["error"] or "")
