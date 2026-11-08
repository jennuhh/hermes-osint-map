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

## Phase 1 — Ships (the layer tonight proved we need) — BUILT 2026-11-07
- **Status: DONE (Baltic live, global awaiting key).** Layer `ships` registered, 310 python tests +
  20 desktop tests green, desktop bundle rebuilt with a dedicated hull glyph (shape 9, points along course).
- **Feed A (live now, keyless):** Finnish Digitraffic open AIS — `meri.digitraffic.fi/api/ais/v1`
  (positions + vessel metadata), CC BY 4.0, ~900 vessels.gzip required. `osintmap/ships.py`.
- **Feed B (awaiting free key):** aisstream.io WebSocket collector — daemon thread, asyncio ws,
  6 h per-MMSI retention, name/type fallback from position reports. Activates when
  `AISSTREAM_API_KEY` is set in the plugin's secret scope (plugin.yaml config_schema).
  GOTCHA verified in code: aisstream puts the fix in `MetaData.latitude/longitude` (lowercase)
  + `ShipName`, NOT in `PositionReport.Latitude`.
- MMSI MID→flag table is deliberately partial (top ~150 flags); an unknown MID gets no country, no guess.
- Heading: true heading when valid (511 = unavailable), else course over ground. Sog 102.3 → null.
- Ships is NOT in watch defaults (an area watch would report every vessel); it is selectable by name.
- Test target when the key lands: Strait of Hormuz tanker traffic + UKMTO advisory incidents.
- PR candidate upstream: YES (keyless Baltic-only core is neutral and useful to everyone).

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
