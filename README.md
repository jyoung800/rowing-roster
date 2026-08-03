# 🚣 Rowing Program — Roller Data API Relay

A thin JSON API in front of your **Roller** account. It handles the OAuth2
client-credentials handshake and reconstructs a "current members" roster from
Roller's data (which has no such endpoint natively — see below), exposing
clean JSON that **Power BI** can pull with a plain Web connector, no OAuth
logic needed on the Power BI side, and your Roller credentials never leave
this server's environment variables.

---

## Why this exists (Roller's API has no "get current members" endpoint)

Roller's Data API is a **per-day changelog**, not a live snapshot. There's no
call that returns "everyone who's currently an active member" — instead:

1. `/data/membershipstatuses?date=X` returns membership status *transitions*
   that happened on that one day (e.g. "this ticket went from New → Current
   on this date"), tied to a `bookingReference`/`ticketId` — no name, no
   product, no expiry.
2. `/bookings/{bookingReference}` (a direct lookup, no date needed) returns
   the **live current state** of that booking — ticket holder, product,
   `membershipStatus`, expiry, `signedWaiverId`.
3. `/customers/{customerId}` (also a direct lookup) returns contact info.

So this server:
- **Discovers** every booking that's ever had a membership event by scanning
  the daily changelog across `LOOKBACK_DAYS` (default 180) days — this is the
  only step that requires per-day scanning, and only runs once as a backfill,
  then incrementally for new days after that (one day per refresh in steady
  state).
- **Enriches only what changed**: the discovery scan already tells us exactly
  which `bookingReference`s had a status-change event on a given day, so
  refreshes only re-fetch *those* bookings (via `/bookings/{ref}` and
  `/customers/{id}`), not the entire historical set. A booking that hasn't
  had an event stays as-is in the cache indefinitely.
- **Filters** to your rowing program's PLU codes (parsed from the product
  name — Roller doesn't expose PLU as its own field, it's embedded like
  `"8573|40 SIBLING | JUNIOR CREW ROWING MEMBERSHIP SPRING SEMESTER"`).
- **Applies semester-based active status at read time, not enrichment time**:
  a membership's active/inactive status depends on today's date (e.g. a Full
  Year membership flips active on Aug 1 with zero Roller-side change), so
  it's computed fresh on every `/api/members`/`/api/summary` call from the
  cached raw fields, rather than baked in when the booking was last enriched.

**Steady-state API usage** (after the one-time backfill): roughly one
`/data/membershipstatuses` call + one `/data/signedwaivers` call per day for
the incremental scan, plus a handful of `/bookings`/`/customers` calls for
whatever actually changed that day. For a small club this is on the order of
single digits to a couple dozen calls/day — a large drop from re-enriching
the entire roster on every refresh (which was costing hundreds of thousands
of calls/month before this design).

---

## Files

| File | What it is |
|------|-----------|
| `server.py` | Python/Flask backend — the whole thing |
| `.env.example` | Template for your API credentials |
| `render.yaml` | Render.com deployment config |
| `requirements.txt` | Python dependencies |
| `README.md` | This guide |

---

## Quick Start

### Step 1 — Get your Roller Data API credentials

1. Log into Roller Venue Manager
2. Go to **Settings → Integrations → API Keys**
3. Click **Create client key**
4. Copy your **Client ID** and **Client Secret**
5. Find your **Venue ID** under **Settings → Account → Venue settings** (used only for display in `/api/health` — Roller's endpoints scope to your account via the token itself, not a `venueId` parameter)

### Step 2 — Configure and run

```bash
# Install dependencies (one time)
pip install -r requirements.txt

# Copy and fill in credentials
cp .env.example .env
# Open .env and paste in your Client ID, Client Secret, Venue ID, and set DEMO_MODE=false

# Run the server
python server.py
```

The first run kicks off a background backfill scan (can take a few minutes —
it's making one API call per day over `LOOKBACK_DAYS`). Check progress at
`/api/health` (`cache_refreshing`, `cache_member_count`, `scanned_through`).

### Step 3 — Deploy to Render (for Power BI to reach it)

Push this repo to GitHub, connect it on [Render.com](https://render.com) as a Web Service,
then add `ROLLER_CLIENT_ID`, `ROLLER_CLIENT_SECRET`, `ROLLER_VENUE_ID` as environment
variables and set `DEMO_MODE=false`. You'll get a public URL like
`https://rowing-roster.onrender.com`.

Use a **single gunicorn worker** (already set in `render.yaml`) — the roster
cache lives in process memory, so multiple workers would each do their own
separate (and much slower, duplicated) backfill.

### Step 4 — Connect from Power BI

1. In Power BI Desktop: **Get Data → Web**
2. Paste `https://rowing-roster.onrender.com/api/members?status=all`
3. Power Query loads the JSON — expand the `data` column into a table
4. Repeat with `/api/waivers` for waiver info, and join on `memberId` / `customerId` if needed
5. Build your visuals, then **Publish** to Power BI Service and share the report link with coaches

---

## API Endpoints

| Endpoint | What it returns |
|----------|----------------|
| `GET /api/summary` | Quick counts: active members, total, waiver count |
| `GET /api/members?status=active` | Full member roster (`active` / `inactive` / `all`), each with `status` (effective), `rollerStatus` (raw), and `scheduleWindow` |
| `GET /api/waivers` | All signed waivers discovered during the scan window, with parent/guardian info resolved for minors |
| `GET /api/products` | The parsed PLU → product name mapping (useful for debugging PLU matches) |
| `GET /api/health` | Mode, venue, PLU filter, and cache status (`cache_built_at`, `cache_refreshing`, `cache_member_count`, `scanned_through`, `last_error`) |
| `POST /api/refresh` | Force a cache rebuild. **Blocks until done** — fine for an already-warm cache (incremental), but a cold 180-day backfill can take several minutes and may exceed a request timeout. Prefer letting the background auto-refresh handle the initial backfill. |

---

## Membership Active-Status Logic

A membership's `status` field is not just Roller's raw status — it's computed from the
membership name:

- Name contains **"spring"** → active only Jan 1 – Jun 30 of that year
- Name contains **"fall"** → active only Aug 1 – Dec 31 of that year
- Name contains **"full year"** / **"annual"** / **"full season"** → active only Aug 1 – Jun 30 (crosses the year boundary)
- No season keyword → falls back to Roller's own live `membershipStatus` (`Current`, `Renewed`, etc. count as active; `Terminated`, `Expired`, `Paused`, etc. count as inactive — see `ACTIVE_ROLLER_STATUSES` in `server.py`)

The year is read from a 4-digit year in the membership name if present (e.g. "Full Year
2025-2026"), otherwise from the booking's start date.

Each roster entry also includes `rollerStatus` (Roller's raw live value) and `scheduleWindow`
(the computed date range) so you can see why a member was marked active/inactive.

---

## Connecting to Roller API Docs

- API Overview: https://mysupport.roller.software/hc/en-us/articles/360001653455-API-overview
- Data API: https://mysupport.roller.software/hc/en-us/articles/360001653475-Data-API
- Full API Reference: https://docs.roller.app/

---

## Troubleshooting

**"401 Unauthorized" errors in server logs**
→ Double-check your Client ID and Secret in `.env`/Render env vars.

**Roster is empty right after startup/deploy**
→ The initial backfill is still running. Check `/api/health` — `cache_refreshing: true` means it's in progress; `cache_member_count` and `scanned_through` show progress. This can take a few minutes on a cold cache.

**Roster is empty even after the backfill finishes**
→ Likely a PLU mismatch. Check `/api/products` to see what PLU codes were actually parsed from your product catalog, and compare against `MEMBERSHIP_PLUS` in `/api/health`.

**A member seems to be missing**
→ If their membership was purchased more than `LOOKBACK_DAYS` ago (default 180) and hasn't had any status change since, the discovery scan won't have found their booking. Increase `LOOKBACK_DAYS` and trigger `/api/refresh`, or wait for the next scheduled backfill.

**Power BI shows a CORS or gateway error**
→ Power BI Desktop's Web connector calls happen server-side (not from a browser), so CORS isn't usually the issue — check the URL is reachable and returns valid JSON first (open it directly in a browser).
