# 🚣 Rowing Program — Member Roster Dashboard

A live roster and attendance dashboard that pulls active memberships, member info, and signed waivers from your **Roller** account.

---

## What It Does

- **Roster** — searchable, sortable table or card grid of all active members
- **Attendance** — check members in for a session with one click; exports to CSV automatically
- **Waivers** — see who has signed a liability or registration waiver
- **Stats bar** — live counts of active members, total members, and signed waivers
- **Demo mode** — works out of the box with sample data even before you connect Roller

---

## Files

| File | What it is |
|------|-----------|
| `dashboard.html` | Open this in any browser — the full UI |
| `server.py` | Python backend that authenticates with Roller and serves data |
| `.env.example` | Template for your API credentials |
| `README.md` | This guide |

---

## Quick Start

### Step 1 — Get your Roller API credentials

1. Log into Roller Venue Manager
2. Go to **Settings → Integrations → API Keys**
3. Click **Create client key**
4. Choose **API Key** type, name it (e.g. "Roster Dashboard"), and generate
5. Copy your **Client ID**, **Client Secret**, and note your **Venue ID**
   (your Venue ID is the numeric ID in your Roller URL, or ask Roller support)

### Step 2 — Set up the backend

```bash
# Install dependencies (one time)
pip install flask flask-cors requests python-dotenv

# Copy and fill in credentials
cp .env.example .env
# Then open .env and paste in your Client ID, Client Secret, and Venue ID

# Run the server
python server.py
```

You should see:
```
🚣 Rowing Roster Dashboard — Backend Server
=============================================
  Venue ID : 12345
  Client ID: abc123...

  Dashboard: open dashboard.html in your browser
  API base : http://localhost:5050/api/
```

### Step 3 — Open the dashboard

Just open `dashboard.html` in your browser (double-click it). It will automatically connect to your local server.

> **No server running?** The dashboard falls back to demo mode with sample data so you can still see how it looks.

---

## API Endpoints (what server.py exposes)

| Endpoint | What it returns |
|----------|----------------|
| `GET /api/summary` | Quick counts: active members, total, waiver count |
| `GET /api/members?status=active` | Full member roster (active / inactive / all) |
| `GET /api/waivers` | All signed waivers |
| `GET /api/waiver-forms` | Waiver form definitions/templates |
| `GET /api/membership-redemptions` | Check-in/redemption history |
| `GET /api/health` | Sanity check — returns `{"status": "ok"}` |

---

## Attendance Workflow

1. Click **Start Attendance** in the toolbar
2. Name the session (e.g. "Morning Practice — July 1")
3. Check the box next to each member as they arrive
4. Click **Save Session** — a CSV is downloaded and the session is logged in the **Attendance Log** tab

---

## Filtering & Search

- **Search bar** — filter by name or email instantly
- **Active / Inactive / All** buttons — switch membership status view
- **Waiver Status** button — cycle through All → Has Waiver → No Waiver
- **Column headers** — click to sort by that column

---

## Connecting to Roller API Docs

- API Overview: https://mysupport.roller.software/hc/en-us/articles/360001653455-API-overview
- Data API: https://mysupport.roller.software/hc/en-us/articles/360001653475-Data-API
- Full API Reference: https://docs.roller.app/

---

## Troubleshooting

**Dashboard shows demo data only**
→ Make sure `server.py` is running and you can reach `http://localhost:5050/api/health` in your browser.

**"401 Unauthorized" errors in server logs**
→ Double-check your Client ID and Secret in `.env`. Credentials are tied to a specific venue.

**Members missing or wrong count**
→ The Data API paginates at 500 records per page. If you have more than 500 members, ask for pagination support to be added.

**CORS error in browser console**
→ Ensure you're opening `dashboard.html` as a file (not from another web server), or add your server's origin to the CORS config in `server.py`.
