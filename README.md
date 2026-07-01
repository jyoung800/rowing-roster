# 🚣 Rowing Program — Roller Data API Relay

A thin JSON API in front of your **Roller** account's Data API. It handles the OAuth2
client-credentials handshake and exposes clean, already-authenticated JSON endpoints —
built so **Power BI** can pull the roster and waiver data with a plain Web connector,
no OAuth logic needed on the Power BI side, and your Roller credentials never leave
this server's environment variables.

---

## What It Does

- Authenticates with Roller's Data API (OAuth2 client-credentials flow)
- Filters memberships down to your rowing program's PLU codes
- Applies semester-based active status: **Spring** (Jan–Jun), **Fall** (Aug–Dec),
  **Full Year** (Aug–Jun) — overriding Roller's own status field where a season is named
  in the membership name; non-seasonal memberships (drop-ins, summer intensives) keep
  Roller's own status
- Resolves parent/guardian info on minors' waivers
- Serves it all as plain JSON, ready for Power BI's Web connector

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
3. Click **Create client key** — make sure it's scoped for the **Data API** (not the REST/booking API)
4. Copy your **Client ID** and **Client Secret**
5. Find your **Venue ID** under **Settings → Account → Venue settings**, or ask Roller support if it's not visible

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

You should see:
```
🚣  Rowing Roster Data API — LIVE (Venue: 12345)
    URL: http://localhost:5050/api/members
```

### Step 3 — Deploy to Render (for Power BI to reach it)

Push this repo to GitHub, connect it on [Render.com](https://render.com) as a Web Service,
then add `ROLLER_CLIENT_ID`, `ROLLER_CLIENT_SECRET`, `ROLLER_VENUE_ID` as environment
variables and set `DEMO_MODE=false`. You'll get a public URL like
`https://rowing-roster.onrender.com`.

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
| `GET /api/waivers` | All signed waivers, with parent/guardian info resolved for minors |
| `GET /api/waiver-forms` | Waiver form definitions/templates |
| `GET /api/membership-redemptions` | Check-in/redemption history |
| `GET /api/health` | Sanity check — mode, venue, PLU filter |

---

## Membership Active-Status Logic

A membership's `status` field is not just Roller's raw status — it's computed from the
membership name:

- Name contains **"spring"** → active only Jan 1 – Jun 30 of that year
- Name contains **"fall"** → active only Aug 1 – Dec 31 of that year
- Name contains **"full year"** / **"annual"** / **"full season"** → active only Aug 1 – Jun 30 (crosses the year boundary)
- No season keyword → falls back to whatever Roller's own status says

The year is read from a 4-digit year in the membership name if present (e.g. "Full Year
2025-2026"), otherwise from the membership's start date.

Each roster entry also includes `rollerStatus` (Roller's raw value) and `scheduleWindow`
(the computed date range) so you can see why a member was marked active/inactive.

---

## Connecting to Roller API Docs

- API Overview: https://mysupport.roller.software/hc/en-us/articles/360001653455-API-overview
- Data API: https://mysupport.roller.software/hc/en-us/articles/360001653475-Data-API
- Full API Reference: https://docs.roller.app/

---

## Troubleshooting

**"401 Unauthorized" errors in server logs**
→ Double-check your Client ID and Secret in `.env`/Render env vars, and confirm the key was created for the **Data API**, not the REST API.

**Members missing or wrong count**
→ The Data API paginates at 500 records per page. If you have more than 500 members, ask for pagination support to be added.

**Roster is empty even though Roller shows active memberships**
→ Likely a PLU field mismatch. Check `/api/health` — it lists the PLU codes being filtered. The server checks `plu`, `productCode`, `sku`, `productPlu`, `externalId`, and `barcode` on each membership record; if Roller uses a different field name, none will match.

**Power BI shows a CORS or gateway error**
→ Power BI Desktop's Web connector calls happen server-side (not from a browser), so CORS isn't usually the issue — check the URL is reachable and returns valid JSON first (open it directly in a browser).
