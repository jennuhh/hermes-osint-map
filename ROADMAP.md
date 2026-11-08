# ROADMAP — OSINT Globe Edition (jennuhh fork)

> Fork of [Adolanium/hermes-osint-map](https://github.com/Adolanium/hermes-osint-map) (MIT).
> Branch `limen-edition` = our edition. Neutral wins get PR'd upstream so Adolanium gets them too.
> Working dir: `/home/jenna/osint-globe-edition`. Upstream sync: cherry-pick only, never blind-sync (state diverges once we add layers).
> Full competitive audit: `~/limen-vault/_infra/design-adoption/OSINT-GLOBE-AUDIT-2026-11-07.md`

## Ethics floor (non-negotiable, from God's Eye View + ours)
**People are not a query type.** Layers model events, assets, infrastructure, systems —
never named-person search, face recognition, or tracking individuals. Every feature below
passes this filter. Adolanium's plugin currently has no person-tracking surface; keep it that way.

## License notes
- Adolanium's code: MIT — keep his copyright notice in LICENSE when we publish.
- God's Eye View: code MIT-safe to borrow patterns from; **bundled datasets are NOT**
  (TeleGeography = CC BY-NC-SA, OI Map = ODbL). Never copy its `src/data/local_data/`.
- OSIRIS: steal only from `carbon-evolution/osiris` (the clean, signed re-publish).
  `simplifaisoul/osiris` (the 11.5k-star original) has a pump.fun address in its repo
  description — provenance-contaminated, do not touch.

## Phase 1 — Ships (the layer tonight proved we need) — BUILT 2026-11-07/08
- **Status: DONE — Baltic (Digitraffic) + Strait of Hormuz (Open Waters) both keyless and live.**
  312 python + 20 desktop tests green; desktop bundle rebuilt with a dedicated hull glyph (shape 9).
- **Feed A (keyless, always on):** Finnish Digitraffic open AIS — Baltic, ~900 vessels, CC BY 4.0.
- **Feed B (keyless, always on):** Open Waters AIS `/v1/stream` — regional box stream, default
  **Strait of Hormuz** (24-28N, 54.5-58.5E; override via `SHIPS_WATCH_BOX` env, minLat,minLon,maxLat,maxLon).
  `snapshot:true` replays last known state so the map is never empty. Per-source licenses
  (NLOD/CC BY 4.0/ODbL), welcome frame with limits, close reasons that say WHY.
- **Feed C (optional):** aisstream.io global when `AISSTREAM_API_KEY` is set — BUT as of Nov 8
  aisstream rejects every subscribe from this server (1006, no close frame, ~1s) while its own
  docs list "invalid key" and its tracker (openwaters.io) records identical mass outages
  (#291, Sep 2026). Key cannot be validated from here. Collector gives it 3 tries per
  reconnect, then settles on Open Waters. If it ever works, global coverage unlocks.
  GOTCHA verified in code: aisstream puts the fix in `MetaData.latitude/longitude` (lowercase)
  + `ShipName`, NOT in `PositionReport.Latitude`. Open Waters /v1 is a DIFFERENT dialect:
  `{"type":"subscribe","bbox":[[minLat,minLon,maxLat,maxLon]]}`; events carry top-level
  mmsi/lat/lon/msg_type with the decoded body under `message`.
- MID table now covers the whole Gulf (AE 470, SA 403, QA 466, KW 447, OM 461, BH 408, YE 473/475,
  PK 463, SY 468, JO 438...) — and FIXED two pre-existing errors: 401 is Afghanistan (was CA),
  403 is Saudi Arabia (was GL), per ITU Appendix 43 + two MID tables.
- Live-verified Nov 8 ~01:00Z: 502 vessels in the collector from the Hormuz box, named/kinded/flagged.
- Ships is NOT in watch defaults (an area watch would report every vessel); it is selectable by name.
- PR candidate upstream: YES (keyless Baltic + Open Waters core is neutral and useful).

## Phase 2 — Fires (NASA FIRMS)
- **Feed:** NASA FIRMS API (free MAP_KEY; data CC0/public domain). VIIRS S-NPP/NOAA-20/21 + MODIS 24h detections.
- Cap hotspots (~3,000 like OSIRIS) for render sanity; ring markers on high-confidence detections.
- Fire perimeters where available: WFIGS/NIFC (US).
- Test target: would have settled the Nov 7 Jask port-fire question from orbit in minutes.
- PR candidate upstream: YES.

## Phase 3 — Heading projection (prerequisite for ships to make sense)
- Steal the PATTERN from GEV `src/data/iconOrientation.js` (per-frame screen-space course
  projection: icons point true real-world heading at every camera angle + horizon cull).
- Reimplement for our globe engine; do not copy bundled data.

## Phase 4 — Cache-first fetching
- Port OSIRIS `cacheFirst.ts` pattern (~100 lines, MIT): hot layer (Redis or sqlite) with
  per-feed TTL → durable snapshots → caller. States hit|stale|miss|bypass.
- Stale-while-revalidate: serve cached instantly, refresh in background; errors never cached;
  minValid() validator rejects degraded payloads, keeps last-known-good, flags source-down.
- Freshness surfaced to UI (badges + "serving cached" banner).
- PR candidate upstream: YES (fixes naive per-request fetching).

## Phase 5 — Quakes upgrade
- Merge EMSC with USGS, dedupe (OSIRIS recipe). Free, keyless, better global coverage.

## Phase 6 — Cross-domain analyst briefing
- Port the FeedGroup pattern: per-layer pre-capped compact rows (`[SECTION — N events]`,
  total passed so the model knows true volume), one serializer, one LLM context.
- Wire into the existing "Brief me" button + agent tools.
- Compound-risk queries: "military flights near conflict zones", "fires near chokepoints".
- PR candidate upstream: YES, with the ethic line quoted in the PR.

## Phase 7 (delight, our-edition-only)
- Liminal Amber reskin: incidents amber (#FFB347) instead of purple, warm-grey halftone globe.
- Cockpit-mode camera (GEV pattern), sensor looks if the globe engine allows GLSL passes.
- Honest-labeling conventions everywhere: RECONSTRUCTED/ESTIMATED tags, staleness surfacing.

## NOT on the roadmap
- Anything from simplifaisoul/osiris.
- Non-commercial-licensed datasets.
- CCTV scraping of geo-restricted government feeds.
- Person tracking / plate data / face recognition. Ever.

## Session start notes (for the next chat)
- Plugin installed + enabled server-side; `osint_*` tools land in NEW sessions only.
- Desktop half installed on Jenna's PC via Install-from-Git (remote-backend split).
- First live test once tools load: `osint_situation` around Hormuz, then Phase 1 spike.
