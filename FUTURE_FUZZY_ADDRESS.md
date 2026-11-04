# Final Digest — BC Fuzzy Geocoding + 211 Reference Centre

## 🎯 The Goal

Build an AI-powered layer over a 211 service directory for British Columbia, with the open-source technology published for adoption by 211 organizations, validated with live data, and—if successful—demonstrated via an in-person Help! reference centre powered by bc211's live records, with their branding and deep links. bc.211.ca is the target partner; nothing nefarious, a referral channel for them.

## 🏗️ The Stack

| Layer | Role | Notes |
|---|---|---|
| **Photon** | Fuzzy typeahead / suggest | Built from a Nominatim dump; typo-tolerant; BC regional index, not planet |
| **Nominatim** | Canonical resolver + reverse geocoding | Resolve by OSM ID; reverse for lat/lon → address |
| **Local HSDS DB + PostGIS** | Service directory + spatial queries | Area search (`ST_Within`) and distance rank (`<->`) |
| **Quantized geo cache** | Fast prefilter | Cell IDs / fixed-point; separate TTL from volatile service metadata |
| **LLM + prompts** | Intent parsing + record-anchored explanation | Picks candidates; never invents facts |
| **Card renderer** | Spoken/printable output | Populated from the record, not from model prose |

## 🔄 The Query Flow

```
User types "Oppen"
  → [debounced] Photon suggests → "Oppenheimer Park, 400 Powell St, Vancouver"
  → user selects
  → Nominatim /lookup?osm_ids=W123456  ← resolve by ID, never by re-parsed string
      → success: canonical record
      → empty: use Photon's coordinates/result (index drift is normal, not an error)
  → nearby services: bbox prefilter (cos-lat corrected, containing box) → haversine rank
  → prompt receives record + nearby set → picks indices
  → tool renders card from record: name, address, hours, eligibility, renewal, link
```

## ⚠️ Decisions That Prevent Known Bugs

- **Resolve by OSM ID, not sanitized string.** String re-query can silently swap the park for the address node at the park.
- **`/lookup` empty = failure.** Crisp, unambiguous. That's why ID lookup beats string re-query.
- **Nominatim only on selection/submit**, never per keystroke. Photon absorbs typeahead load.
- **Bbox must contain the circle:** `Δlon = Δlat / cos(lat)` + margin. Under-inclusion drops valid nearest neighbors; over-inclusion is harmless.
- **Haversine on survivors only.** Haversine's ~0.5% error is invisible for ranking; don't reach for Vincenty.
- **Session-unique candidate indices**, frozen per turn. Index-only handoff is an off-by-refresh bug.
- **Nearby set is fetched, not inferred.** The record can't tell you what's nearby; the spatial layer must inject it.
- **Renewal location: structured field → quote verbatim; free text → "not stated, see link."** Never infer.
- **Missing-field language:** `n/a` for cosmetic fields; **"not stated — check link"** for eligibility, hours, renewal. "n/a" reads as "no restrictions" to a hurried worker.
- **Log every answer** with record ID, nearby-set IDs, prompt version, and output text. Non-negotiable for audit and for defending the system.

## 📊 Metrics for the Pilot

**Per session:**
- Sessions started (N)
- Sessions completed — finish button pressed (M). *This is a flow metric, not a success metric.*
- Beads: **good / couldn't-find / bad** — three states, not two. Denominator = N.
- Time-to-referral — the stopwatch number that proves the stack works.

**Quarterly report to bc211** (one page, framed around their questions):
1. Reach: started / completed / abandoned
2. Resolution: % queries resolved; median time-to-referral
3. Satisfaction: bead ratio with denominator
4. **Gaps: top categories users asked for that the directory doesn't cover** ← the section they'll read first
5. Staleness: how often staff flagged a record; how fast refresh fixed it
6. Referral traffic: clicks through to bc.211.ca records

**Aggregation rules:** no cell below n=5; no free-text in shared reports; raw logs stay local; retention window stated (e.g., 90 days).

## 🤝 The bc211 Partnership Ask

**What you're asking for:** limited read access (~1,000 requests) to finish and validate the connector against real response shapes.

**What you're offering:**
- An **open-source connector**, agnostic to which 211 instance it talks to — bc211 can adopt it; so can Ontario, Alberta, any United Way.
- **Referral traffic and brand visibility** — every card sends a user to their canonical record.
- **A gap list** — free market research on what their directory doesn't cover.
- **A distribution channel** they don't currently have in that form.

**What you won't do:** redistribute their data, scrape beyond the agreed cadence, use their branding outside the pilot.

**The ~1,000 request breakdown:** ~600 connector development against real shapes, ~200 pagination/edge cases, ~200 initial duplication + verification. After that: refresh no more than monthly, scheduled at their convenience. **Local cache means their load is O(refresh cadence), not O(users)** — lead with this.

## 🧾 Licensing Split (Resolve Before Publishing)

- **Code in git, data out of git.** `fetch.sh` / `load.py` pulls from their source under their terms.
- **Code license:** MIT or Apache-2.0.
- **Directory data:** whatever license bc211 specifies.
- **ODbL overlay:** the lat/lon enrichment derived from Nominatim is arguably a Derivative Database under ODbL; share-alike attaches to the database, not your code. State this explicitly in the project licensing, or you'll have a compliance problem on first redistribution. Thirty minutes with someone who knows ODbL, before publishing.

## 🎬 The Demo

Lead with **query understanding**, not the geocoder. Worker types a messy real query → system resolves location → filters by area or radius → ranks by distance → shows cards with distance and a map → selection → Nominatim reverse fills the address for the call script.

Rehearse the failure paths: no location in query, ambiguous area ("Victoria" the city vs. the street), address that doesn't geocode. Front-line workers hit these on day one; graceful failure is more persuasive than a perfect happy path.

## 🗺️ Rollout Sequence

1. Build the connector against **mock data first** — don't spend the 1,000 requests on shapes you can infer from public pages.
2. Stand up Photon with a **BC regional index** (Docker, pinned community image — not official Komoot).
3. Wire suggest (debounced) and resolve (`/lookup` by OSM ID + Photon fallback).
4. Load HSDS data locally, index with PostGIS, run bbox + haversine.
5. Run the prompt test set: hours, ID, kids, renewal — record present *and* absent. If the model answers confidently without a field, tighten the prompt.
6. Ask bc211 for limited access with a **one-page LOI**: access scope, rate, what you'll publish, what you won't do, attribution spec, refresh cadence, accuracy disclaimer, end-of-pilot data handling.
7. Validate with live data; measure geocode hit rate and query resolution rate.
8. Pilot — community and front-line worker feedback, accuracy and staleness metrics.
9. Open the centre **only if the pilot numbers justify it**. The centre is the demo, not the prerequisite.

## 💎 What You Are *Not* Building

No dictionary prefilter, no custom fuzzy matching, no candidate-generation or ranking logic on your side. Photon owns fuzzy; Nominatim owns canonical truth; PostGIS owns spatial; the LLM picks from a frozen candidate set; the card renders from the record. **You own the glue: debounce, ID handoff, fallback, stable interface, and the audit log.**

## ⏭️ Open Items

- **Anti-scraping posture:** ask bc211 before any snapshot, even informally. "We already scraped your whole directory" is a bad opening line.
- **Identity key for the shadow overlay:** stable IDs if exposed; otherwise composite (name + address + phone) with fuzzy re-matching and a manual review queue on refresh. This is the main maintenance cost of the shadow approach.
- **Fetch boundary for bc.211.ca:** connector-only, so the repo stays clean — but confirm their terms before the first bulk snapshot.
- **ODbL consultation** before publishing the overlay.

---

The through-line: **Photon suggests, Nominatim resolves, PostGIS ranks, the model picks, the card renders from the record, and the gap list is the gift.** Everything else is glue you can change without touching the geocoder or the ranker.