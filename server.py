"""
Rowing Program Roster Data API — Roller relay for Power BI
===========================================================
A thin JSON API in front of ROLLER's Data API. It handles the OAuth2
client-credentials flow (painful to reimplement in Power Query/M) and
exposes clean JSON endpoints that Power BI's Web connector can read
directly, with no auth logic needed on the Power BI side.

LOCAL:  python server.py  →  http://localhost:5050/api/members
CLOUD:  Deployed on Render (see README).

Endpoints: /api/members, /api/waivers, /api/summary, /api/health

Dependencies: pip install flask flask-cors requests python-dotenv gunicorn
"""

import os
import re
import time
import threading
import requests
from datetime import datetime, timezone, date, timedelta
from functools import wraps
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
DEMO_MODE            = os.getenv("DEMO_MODE", "false").lower() == "true"
ROLLER_CLIENT_ID     = os.getenv("ROLLER_CLIENT_ID",     "")
ROLLER_CLIENT_SECRET = os.getenv("ROLLER_CLIENT_SECRET", "")
ROLLER_VENUE_ID      = os.getenv("ROLLER_VENUE_ID",      "")
PORT                 = int(os.getenv("PORT", 5050))

_plu_env        = os.getenv("MEMBERSHIP_PLUS", "8565,8572,8573,8574,8575,8579,9528,9529,9530,9531,9547,9548,9549,9550")
MEMBERSHIP_PLUS = [p.strip() for p in _plu_env.split(",") if p.strip()]

ROLLER_TOKEN_URL = "https://api.roller.app/token"
ROLLER_DATA_API  = "https://api.roller.app"

# Roller's Data API has no "current members" snapshot — /data/membershipstatuses
# is a per-day changelog of status transitions. LOOKBACK_DAYS controls how far
# back the one-time historical scan looks to catch every booking that might
# still be currently active (e.g. a Full Year membership bought months ago).
LOOKBACK_DAYS     = int(os.getenv("LOOKBACK_DAYS", "180"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(6 * 3600)))

# Membership statuses (from Roller's docs, plus our own "active" demo-data
# convention) that count as "currently active" when a membership's name has
# no season keyword to override with.
ACTIVE_ROLLER_STATUSES = {"active", "current", "renewed", "groupmembership", "pending pause"}

# ─────────────────────────────────────────────────────────────────────────────
# Demo data — realistic sample roster for testing
# ─────────────────────────────────────────────────────────────────────────────
DEMO_MEMBERS_DATA = [
    {"memberId":"1001","firstName":"Alex",    "lastName":"Chen",      "fullName":"Alex Chen",       "email":"alex.chen@email.com",    "phone":"555-234-5678","membershipName":"Competitive Rower — Full Year 2025-2026",  "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-03","endDate":"2026-12-31","plu":"8565"},
    {"memberId":"1002","firstName":"Jordan",  "lastName":"Rivera",    "fullName":"Jordan Rivera",   "email":"j.rivera@email.com",     "phone":"555-345-6789","membershipName":"Recreational Rower — Fall 2025 Semester", "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-05","endDate":"2026-09-15","plu":"8572"},
    {"memberId":"1003","firstName":"Sam",     "lastName":"Okonkwo",   "fullName":"Sam Okonkwo",     "email":"sam.o@email.com",        "phone":"555-456-7890","membershipName":"Youth Program — Spring 2026 Semester",      "status":"active",  "hasWaiver":False,"waiverDate":None,        "endDate":"2026-08-31","plu":"8573"},
    {"memberId":"1004","firstName":"Morgan",  "lastName":"Walsh",     "fullName":"Morgan Walsh",    "email":"morgan.w@email.com",     "phone":"555-567-8901","membershipName":"Competitive Rower — Full Year 2025-2026",  "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-05","endDate":"2026-12-31","plu":"8565"},
    {"memberId":"1005","firstName":"Taylor",  "lastName":"Kim",       "fullName":"Taylor Kim",      "email":"taylor.k@email.com",     "phone":"555-678-9012","membershipName":"Masters Rower — Summer Intensive",          "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-10","endDate":"2027-01-15","plu":"8574"},
    {"memberId":"1006","firstName":"Casey",   "lastName":"Patel",     "fullName":"Casey Patel",     "email":"casey.p@email.com",      "phone":"555-789-0123","membershipName":"Recreational Rower — Fall 2025 Semester", "status":"active",  "hasWaiver":False,"waiverDate":None,        "endDate":"2026-10-01","plu":"8572"},
    {"memberId":"1007","firstName":"Jamie",   "lastName":"Thompson",  "fullName":"Jamie Thompson",  "email":"jamie.t@email.com",      "phone":"555-890-1234","membershipName":"Youth Program — Spring 2026 Semester",      "status":"active",  "hasWaiver":True, "waiverDate":"2026-02-01","endDate":"2026-08-31","plu":"8573"},
    {"memberId":"1008","firstName":"Riley",   "lastName":"Anderson",  "fullName":"Riley Anderson",  "email":"riley.a@email.com",      "phone":"555-901-2345","membershipName":"Masters Rower — Full Year 2026-2027",      "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-12","endDate":"2027-02-28","plu":"8574"},
    {"memberId":"1009","firstName":"Drew",    "lastName":"Garcia",    "fullName":"Drew Garcia",     "email":"drew.g@email.com",       "phone":"555-012-3456","membershipName":"Competitive Rower — Adult Drop-In Pass",   "status":"active",  "hasWaiver":False,"waiverDate":None,        "endDate":"2026-12-31","plu":"8565"},
    {"memberId":"1010","firstName":"Avery",   "lastName":"Martinez",  "fullName":"Avery Martinez",  "email":"avery.m@email.com",      "phone":"555-123-4568","membershipName":"Recreational Rower — Fall 2025 Semester", "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-15","endDate":"2026-11-30","plu":"8572"},
    {"memberId":"1011","firstName":"Quinn",   "lastName":"Johnson",   "fullName":"Quinn Johnson",   "email":"quinn.j@email.com",      "phone":"555-234-5679","membershipName":"Competitive Rower — Full Year 2025-2026",  "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-08","endDate":"2026-12-31","plu":"8565"},
    {"memberId":"1012","firstName":"Parker",  "lastName":"Lee",       "fullName":"Parker Lee",      "email":"parker.l@email.com",     "phone":"555-345-6780","membershipName":"Youth Program — Spring 2026 Semester",      "status":"active",  "hasWaiver":False,"waiverDate":None,        "endDate":"2026-08-31","plu":"8573"},
    {"memberId":"1013","firstName":"Reese",   "lastName":"Wilson",    "fullName":"Reese Wilson",    "email":"reese.w@email.com",      "phone":"555-456-7891","membershipName":"Masters Rower — Full Year 2024-2025",      "status":"inactive","hasWaiver":True, "waiverDate":"2025-01-20","endDate":"2025-12-01","plu":"8574"},
    {"memberId":"1014","firstName":"Skylar",  "lastName":"Brown",     "fullName":"Skylar Brown",    "email":"skylar.b@email.com",     "phone":"555-567-8902","membershipName":"Recreational Rower — Fall 2024 Semester", "status":"inactive","hasWaiver":False,"waiverDate":None,        "endDate":"2025-11-15","plu":"8572"},
    {"memberId":"1015","firstName":"Cameron", "lastName":"Davis",     "fullName":"Cameron Davis",   "email":"cam.d@email.com",        "phone":"555-678-9013","membershipName":"Competitive Rower — Full Year 2025-2026",  "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-20","endDate":"2026-12-31","plu":"8565"},
    {"memberId":"1016","firstName":"Rowan",   "lastName":"Foster",    "fullName":"Rowan Foster",    "email":"rowan.f@email.com",      "phone":"555-789-0124","membershipName":"Youth Program — Spring 2026 Semester",      "status":"active",  "hasWaiver":True, "waiverDate":"2026-02-10","endDate":"2026-08-31","plu":"8573"},
    {"memberId":"1017","firstName":"Peyton",  "lastName":"Hughes",    "fullName":"Peyton Hughes",   "email":"peyton.h@email.com",     "phone":"555-890-1235","membershipName":"Masters Rower — Summer Intensive",          "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-25","endDate":"2027-01-31","plu":"8574"},
    {"memberId":"1018","firstName":"Sage",    "lastName":"Nguyen",    "fullName":"Sage Nguyen",     "email":"sage.n@email.com",       "phone":"555-901-2346","membershipName":"Recreational Rower — Fall 2025 Semester", "status":"active",  "hasWaiver":False,"waiverDate":None,        "endDate":"2026-10-15","plu":"8572"},
    {"memberId":"1019","firstName":"Blake",   "lastName":"Ortiz",     "fullName":"Blake Ortiz",     "email":"blake.o@email.com",      "phone":"555-012-3457","membershipName":"Competitive Rower — Full Year 2025-2026",  "status":"active",  "hasWaiver":True, "waiverDate":"2026-01-30","endDate":"2026-12-31","plu":"8579"},
    {"memberId":"1020","firstName":"Dakota",  "lastName":"Price",     "fullName":"Dakota Price",    "email":"dakota.p@email.com",     "phone":"555-123-4569","membershipName":"Youth Program — Spring 2026 Semester",      "status":"active",  "hasWaiver":False,"waiverDate":None,        "endDate":"2026-08-31","plu":"8573"},
]

DEMO_WAIVERS_DATA = [
    {"signedWaiverId":"w001","customerId":"1001","firstName":"Alex",    "lastName":"Chen",     "email":"alex.chen@email.com",   "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-03","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w002","customerId":"1002","firstName":"Jordan",  "lastName":"Rivera",   "email":"j.rivera@email.com",    "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-05","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w003","customerId":"1003","firstName":"Sam",     "lastName":"Okonkwo",  "email":"sam.o@email.com",       "waiverName":"Youth Participant Waiver","signedAt":"2026-02-01","isMinor":True, "parentFirstName":"David","parentLastName":"Okonkwo","parentEmail":"david.o@email.com","customFields":{"emergencyContact":"555-111-2222","medicalNotes":"None"}},
    {"signedWaiverId":"w004","customerId":"1004","firstName":"Morgan",  "lastName":"Walsh",    "email":"morgan.w@email.com",    "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-05","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w005","customerId":"1005","firstName":"Taylor",  "lastName":"Kim",      "email":"taylor.k@email.com",    "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-10","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w006","customerId":"1007","firstName":"Jamie",   "lastName":"Thompson", "email":"jamie.t@email.com",     "waiverName":"Youth Participant Waiver","signedAt":"2026-02-01","isMinor":True, "parentFirstName":"Lisa","parentLastName":"Thompson","parentEmail":"lisa.t@email.com","customFields":{"emergencyContact":"555-333-4444","medicalNotes":"EpiPen required"}},
    {"signedWaiverId":"w007","customerId":"1008","firstName":"Riley",   "lastName":"Anderson", "email":"riley.a@email.com",     "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-12","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w008","customerId":"1010","firstName":"Avery",   "lastName":"Martinez", "email":"avery.m@email.com",     "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-15","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w009","customerId":"1011","firstName":"Quinn",   "lastName":"Johnson",  "email":"quinn.j@email.com",     "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-08","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w010","customerId":"1015","firstName":"Cameron", "lastName":"Davis",    "email":"cam.d@email.com",       "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-20","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w011","customerId":"1016","firstName":"Rowan",   "lastName":"Foster",   "email":"rowan.f@email.com",     "waiverName":"Youth Participant Waiver","signedAt":"2026-02-10","isMinor":True, "parentFirstName":"Chris","parentLastName":"Foster","parentEmail":"chris.f@email.com","customFields":{"emergencyContact":"555-555-6666","medicalNotes":"Asthma — inhaler on site"}},
    {"signedWaiverId":"w012","customerId":"1017","firstName":"Peyton",  "lastName":"Hughes",   "email":"peyton.h@email.com",    "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-25","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
    {"signedWaiverId":"w013","customerId":"1019","firstName":"Blake",   "lastName":"Ortiz",    "email":"blake.o@email.com",     "waiverName":"2026 Liability Waiver",   "signedAt":"2026-01-30","isMinor":False,"parentFirstName":"","parentLastName":"","parentEmail":"","customFields":{}},
]


# ─────────────────────────────────────────────────────────────────────────────
# Membership schedule rules
#
# Coaches don't just trust Roller's own "active" flag — a membership is only
# actually active during the season it was sold for, regardless of what
# Roller's status/end date say:
#   - "Spring" memberships run Jan 1 – Jun 30
#   - "Fall" memberships run Aug 1 – Dec 31
#   - "Full Year" memberships run Aug 1 – Jun 30 (never July, win or lose)
# Anything that doesn't mention a season (drop-in passes, summer intensives,
# etc.) keeps whatever status Roller reports.
# ─────────────────────────────────────────────────────────────────────────────
FULL_YEAR_KEYWORDS = ("full year", "full-year", "full season", "annual", "year round", "year-round")
SPRING_KEYWORDS    = ("spring",)
FALL_KEYWORDS      = ("fall",)


def _season_type(membership_name: str):
    name = (membership_name or "").lower()
    if any(k in name for k in FULL_YEAR_KEYWORDS):
        return "full_year"
    if any(k in name for k in SPRING_KEYWORDS):
        return "spring"
    if any(k in name for k in FALL_KEYWORDS):
        return "fall"
    return None


def _extract_year(text: str):
    match = re.search(r"20\d{2}", text or "")
    return int(match.group()) if match else None


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def compute_schedule(membership_name: str, start_date_str, today: date):
    """Returns None if the membership name has no season keyword (no override),
    otherwise {"active": bool, "window": "Aug 01, 2025 - Jun 30, 2026"}."""
    season = _season_type(membership_name)
    if season is None:
        return None

    year = _extract_year(membership_name)
    if year is None:
        start_date = _parse_date(start_date_str)
        year = start_date.year if start_date else today.year

    if season == "spring":
        window_start, window_end = date(year, 1, 1), date(year, 6, 30)
    elif season == "fall":
        window_start, window_end = date(year, 8, 1), date(year, 12, 31)
    else:  # full_year — Aug of `year` through Jun of `year + 1`
        window_start, window_end = date(year, 8, 1), date(year + 1, 6, 30)

    return {
        "active": window_start <= today <= window_end,
        "window": f"{window_start.strftime('%b %d, %Y')} - {window_end.strftime('%b %d, %Y')}",
    }


def resolve_status(membership_name: str, start_date_str, roller_status: str, today: date | None = None):
    """Returns (effective_status, schedule_window_or_None)."""
    today = today or datetime.now(timezone.utc).date()
    schedule = compute_schedule(membership_name, start_date_str, today)
    if schedule is not None:
        return ("active" if schedule["active"] else "inactive"), schedule["window"]
    normalized = (roller_status or "").strip().lower()
    return ("active" if normalized in ACTIVE_ROLLER_STATUSES else "inactive"), None


# ─────────────────────────────────────────────────────────────────────────────
# Token cache (live mode only)
# ─────────────────────────────────────────────────────────────────────────────
_token_cache: dict = {"token": None, "expires_at": 0.0}


def get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 30:
        return _token_cache["token"]
    resp = requests.post(ROLLER_TOKEN_URL, json={
        "client_id":     ROLLER_CLIENT_ID,
        "client_secret": ROLLER_CLIENT_SECRET,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"]      = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["token"]


def roller_get(path: str, params: dict | None = None, timeout: int = 15):
    """GET against api.roller.app with auto token-refresh on 401. Returns
    parsed JSON (dict or list, depending on the endpoint) or None on 404."""
    token = get_access_token()
    for attempt in range(2):
        resp = requests.get(
            f"{ROLLER_DATA_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=timeout,
        )
        if resp.status_code == 401 and attempt == 0:
            _token_cache["token"] = None
            token = get_access_token()
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Roster cache (live mode)
#
# Roller's Data API has no "give me current members" endpoint — the only
# membership-related data it exposes is a per-day changelog. So the pipeline
# is:
#   1. DISCOVER — scan /data/membershipstatuses?date=X and /data/signedwaivers
#      ?date=X across LOOKBACK_DAYS days to find every bookingReference that's
#      ever had a membership event, and every signed waiver.
#   2. ENRICH — for each discovered booking, call /bookings/{ref} directly
#      (no date needed) to get the LIVE current status, ticket holder, product,
#      and expiry — then /customers/{id} for contact info.
#   3. FILTER — keep only tickets whose product matches one of our PLUs (PLU
#      is parsed from the product name, e.g. "8573|40 ... SPRING SEMESTER").
# This is too slow to run per-request, so results are cached in memory and
# refreshed in the background when stale.
# ─────────────────────────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_roster_cache = {
    "members":          [],
    "waivers":          [],
    "known_booking_refs": set(),
    "scanned_through":  None,   # date — last day included in the discovery scan
    "products_by_id":   {},     # productId(str) -> {"plu": str, "name": str}
    "products_loaded_at": 0.0,
    "built_at":          0.0,
    "refreshing":        False,
    "last_error":        None,
}


def load_product_catalog(force: bool = False):
    if not force and _roster_cache["products_by_id"] and time.time() - _roster_cache["products_loaded_at"] < 24 * 3600:
        return
    catalog = roller_get("/products", timeout=30) or []
    mapping = {}
    for parent in catalog:
        for variant in parent.get("products", []):
            vid  = str(variant.get("id", ""))
            name = variant.get("name") or parent.get("name") or ""
            match = re.match(r"^(\d+)\|\S*\s*(.*)$", name)
            if match:
                plu, readable = match.group(1), match.group(2).strip() or name
            else:
                plu, readable = "", name
            if vid:
                mapping[vid] = {"plu": plu, "name": readable}
    _roster_cache["products_by_id"]   = mapping
    _roster_cache["products_loaded_at"] = time.time()


def _scan_changelog_day(d: date):
    """One day of both changelogs. Tolerates a single bad day (network hiccup,
    transient error) so it doesn't stall the whole backfill.

    /data/membershipstatuses takes a single `date` and returns a bare array.
    /data/signedwaivers takes a `startDate`/`endDate` 1-day span and returns
    a paginated {"items": [...], "totalPages": N} wrapper — two different
    conventions on the same API, confirmed against the live account."""
    try:
        events = roller_get("/data/membershipstatuses", {"date": d.isoformat()}) or []
        for e in events:
            ref = e.get("bookingReference")
            if ref:
                _roster_cache["known_booking_refs"].add(str(ref))
    except requests.RequestException:
        pass
    try:
        next_day = d + timedelta(days=1)
        page = 1
        while True:
            resp = roller_get("/data/signedwaivers", {
                "startDate": d.isoformat(), "endDate": next_day.isoformat(), "page": page,
            }) or {}
            items = resp.get("items", [])
            _roster_cache["waivers"].extend(items)
            if page >= resp.get("totalPages", 0):
                break
            page += 1
    except requests.RequestException:
        pass


def _discover_membership_bookings():
    today = datetime.now(timezone.utc).date()
    scanned_through = _roster_cache["scanned_through"]
    start_day = (today - timedelta(days=LOOKBACK_DAYS)) if scanned_through is None else (scanned_through + timedelta(days=1))
    if scanned_through is not None and start_day > today:
        return  # already fully scanned through today
    d = start_day
    while d <= today:
        _scan_changelog_day(d)
        # Checkpoint after every day so a slow/interrupted backfill doesn't
        # have to restart from scratch, and progress is visible in /api/health.
        _roster_cache["scanned_through"] = d
        d += timedelta(days=1)


def _clean_booking_name(name: str) -> str:
    """Booking names sometimes carry extra descriptive text, e.g.
    "Madeline Glover- FA Annual Membership" -> "Madeline Glover"."""
    return re.split(r"\s*-\s*", name or "", maxsplit=1)[0].strip()


def _split_name(full: str):
    parts = full.split(None, 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (full, "")


def _build_roster_entry(ref: str, item: dict, ticket: dict, product: dict, ticket_customer: dict, booking_customer: dict, booking_name: str, today: date):
    ticket_cid  = str(ticket_customer.get("customerId") or "")
    booking_cid = str(booking_customer.get("customerId") or "")
    resolved_name = f"{ticket_customer.get('firstName','')} {ticket_customer.get('lastName','')}".strip()

    # A ticket with its own customerId usually means Roller has a real
    # profile for the ticket holder (not just the purchaser) -- trust it.
    # Otherwise the resolved customer is often the parent/purchaser, so
    # prefer the ticket's own name fields or the booking's typed name
    # (which is frequently the actual rower's name even on a parent's
    # account) before falling back to the purchaser's name.
    if ticket_cid and resolved_name:
        first, last = ticket_customer.get("firstName", ""), ticket_customer.get("lastName", "")
        full_name = resolved_name
    else:
        booking_resolved = f"{booking_customer.get('firstName','')} {booking_customer.get('lastName','')}".strip()
        name_source = ticket.get("ticketHolderName") or ticket.get("name") or _clean_booking_name(booking_name) or booking_resolved
        full_name = name_source or "Unknown"
        first, last = _split_name(full_name) if full_name != "Unknown" else ("", "")

    # The ticket holder's own profile (a minor) often lacks contact info --
    # fall back to the purchaser's (usually a parent), which is who a coach
    # would want to reach anyway.
    email = ticket_customer.get("email") or booking_customer.get("email", "")
    phone = ticket_customer.get("phone") or booking_customer.get("phone", "")

    effective_status, window = resolve_status(
        product["name"], item.get("bookingDate"), ticket.get("membershipStatus", ""), today
    )
    return {
        "memberId":       ticket_cid or booking_cid or ticket.get("ticketId", ""),
        "firstName":      first,
        "lastName":       last,
        "fullName":       full_name,
        "email":          email,
        "phone":          phone,
        "membershipName": product["name"],
        "status":         effective_status,
        "rollerStatus":   ticket.get("membershipStatus", ""),
        "scheduleWindow": window,
        "startDate":      item.get("bookingDate", ""),
        "endDate":         item.get("bookingEndDate", ""),
        "plu":            product["plu"],
        "hasWaiver":      bool(ticket.get("signedWaiverId")),
        "waiverDate":     None,
        "bookingReference": ref,
        "ticketId":       ticket.get("ticketId", ""),
    }


def _enrich_roster():
    load_product_catalog()
    today = datetime.now(timezone.utc).date()
    customer_cache: dict = {}
    roster = []
    for ref in list(_roster_cache["known_booking_refs"]):
        try:
            booking = roller_get(f"/bookings/{ref}")
        except requests.RequestException:
            continue
        if not booking:
            continue
        booking_cid  = str(booking.get("customerId") or "")
        booking_name = booking.get("name", "")

        def fetch_customer(cid: str) -> dict:
            if not cid:
                return {}
            if cid not in customer_cache:
                try:
                    customer_cache[cid] = roller_get(f"/customers/{cid}") or {}
                except requests.RequestException:
                    customer_cache[cid] = {}
            return customer_cache[cid]

        booking_customer = fetch_customer(booking_cid)
        for item in booking.get("items", []):
            pid = str(item.get("productId", ""))
            product = _roster_cache["products_by_id"].get(pid)
            if not product:
                continue
            if MEMBERSHIP_PLUS and product["plu"] not in MEMBERSHIP_PLUS:
                continue
            for ticket in item.get("tickets", []):
                # Membership tickets often don't carry their own customerId,
                # and even when they do, that profile (the actual rower --
                # frequently a minor) may lack contact info. Resolve both the
                # ticket's own customer and the booking's purchaser so name
                # and contact info can be picked independently.
                ticket_cid = str(ticket.get("customerId") or "")
                ticket_customer = fetch_customer(ticket_cid) if ticket_cid else {}
                roster.append(_build_roster_entry(ref, item, ticket, product, ticket_customer, booking_customer, booking_name, today))
    roster.sort(key=lambda x: (x["lastName"].lower(), x["firstName"].lower()))
    _roster_cache["members"] = roster


def refresh_roster_cache():
    if not _cache_lock.acquire(blocking=False):
        return  # a refresh is already running
    try:
        _roster_cache["refreshing"] = True
        _discover_membership_bookings()
        _enrich_roster()
        _roster_cache["built_at"]   = time.time()
        _roster_cache["last_error"] = None
    except Exception as e:
        _roster_cache["last_error"] = str(e)
    finally:
        _roster_cache["refreshing"] = False
        _cache_lock.release()


def ensure_roster_fresh():
    """Serves instantly from cache; kicks off a background refresh if stale
    (or if this is the very first request) without blocking the response."""
    is_stale = time.time() - _roster_cache["built_at"] > CACHE_TTL_SECONDS
    if is_stale and not _roster_cache["refreshing"]:
        threading.Thread(target=refresh_roster_cache, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic — a single fast, timed round-trip to Roller, to isolate network
# issues from the (much slower) background backfill.
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/diag")
def diag():
    if DEMO_MODE:
        return jsonify({"message": "Demo mode"})
    steps = {}
    t0 = time.time()
    try:
        token = get_access_token()
        steps["token"] = {"ok": True, "seconds": round(time.time() - t0, 2), "token_len": len(token)}
    except Exception as e:
        steps["token"] = {"ok": False, "seconds": round(time.time() - t0, 2), "error": str(e)}
        return jsonify(steps), 200
    t1 = time.time()
    try:
        events = roller_get("/data/membershipstatuses", {"date": datetime.now(timezone.utc).date().isoformat()}, timeout=10)
        steps["single_day_scan"] = {"ok": True, "seconds": round(time.time() - t1, 2), "event_count": len(events or [])}
    except Exception as e:
        steps["single_day_scan"] = {"ok": False, "seconds": round(time.time() - t1, 2), "error": str(e)}
    return jsonify(steps)


# ─────────────────────────────────────────────────────────────────────────────
# Error decorator
# ─────────────────────────────────────────────────────────────────────────────
def handle_errors(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 502
            body = e.response.text[:500] if e.response is not None else ""
            return jsonify({"error": str(e), "roller_response": body, "status": code}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# API — health
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    cache_info = {} if DEMO_MODE else {
        "cache_built_at":  datetime.fromtimestamp(_roster_cache["built_at"], tz=timezone.utc).isoformat() if _roster_cache["built_at"] else None,
        "cache_refreshing": _roster_cache["refreshing"],
        "cache_member_count": len(_roster_cache["members"]),
        "known_bookings_discovered": len(_roster_cache["known_booking_refs"]),
        "scanned_through": _roster_cache["scanned_through"].isoformat() if _roster_cache["scanned_through"] else None,
        "last_error":      _roster_cache["last_error"],
    }
    return jsonify({
        "status":      "ok",
        "mode":        "demo" if DEMO_MODE else "live",
        "venue_id":    ROLLER_VENUE_ID or "(demo)",
        "plu_filter":  MEMBERSHIP_PLUS,
        "plu_count":   len(MEMBERSHIP_PLUS),
        **cache_info,
    })


# ─────────────────────────────────────────────────────────────────────────────
# API — force a cache refresh (blocks until done — can take a couple minutes
# on a cold cache since it's scanning LOOKBACK_DAYS of changelog history)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/refresh", methods=["POST"])
@handle_errors
def refresh():
    if DEMO_MODE:
        return jsonify({"message": "Demo mode — nothing to refresh"})
    refresh_roster_cache()
    return jsonify({
        "built_at": _roster_cache["built_at"],
        "member_count": len(_roster_cache["members"]),
        "error": _roster_cache["last_error"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# API — summary
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/summary")
@handle_errors
def get_summary():
    if DEMO_MODE:
        today = datetime.now(timezone.utc).date()
        active = sum(
            1 for m in DEMO_MEMBERS_DATA
            if resolve_status(m["membershipName"], m.get("startDate"), m["status"], today)[0] == "active"
        )
        return jsonify({
            "activeMembers":   active,
            "inactiveMembers": len(DEMO_MEMBERS_DATA) - active,
            "totalMembers":    len(DEMO_MEMBERS_DATA),
            "signedWaivers":   len(DEMO_WAIVERS_DATA),
            "asOf":            datetime.now(timezone.utc).isoformat(),
        })

    ensure_roster_fresh()
    members = _roster_cache["members"]
    active  = sum(1 for m in members if m["status"] == "active")
    return jsonify({
        "activeMembers":   active,
        "inactiveMembers": len(members) - active,
        "totalMembers":    len(members),
        "signedWaivers":   len(_roster_cache["waivers"]),
        "asOf":            datetime.fromtimestamp(_roster_cache["built_at"], tz=timezone.utc).isoformat() if _roster_cache["built_at"] else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
# API — members roster
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/members")
@handle_errors
def get_members():
    status_filter = request.args.get("status", "active").lower()
    search        = request.args.get("search", "").lower()
    today         = datetime.now(timezone.utc).date()

    if DEMO_MODE:
        roster = []
        for m in DEMO_MEMBERS_DATA:
            entry = dict(m)
            effective_status, window = resolve_status(entry["membershipName"], entry.get("startDate"), entry["status"], today)
            entry["rollerStatus"]   = entry["status"]
            entry["status"]         = effective_status
            entry["scheduleWindow"] = window
            roster.append(entry)
    else:
        ensure_roster_fresh()
        roster = [dict(m) for m in _roster_cache["members"]]

    if status_filter != "all":
        roster = [m for m in roster if m["status"] == status_filter]
    if search:
        roster = [m for m in roster if search in m["fullName"].lower() or search in m["email"].lower()]
    roster = sorted(roster, key=lambda x: (x["lastName"].lower(), x["firstName"].lower()))
    return jsonify({"total": len(roster), "status": status_filter, "data": roster})


# ─────────────────────────────────────────────────────────────────────────────
# API — waivers
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/waivers")
@handle_errors
def get_waivers():
    if DEMO_MODE:
        return jsonify({"total": len(DEMO_WAIVERS_DATA), "data": DEMO_WAIVERS_DATA})

    ensure_roster_fresh()
    waivers  = _roster_cache["waivers"]
    id_map   = {str(w.get("signedWaiverId", w.get("id", ""))): w for w in waivers}
    enriched = []
    for w in waivers:
        entry = {
            "signedWaiverId":  w.get("signedWaiverId") or w.get("id"),
            "customerId":      w.get("customerId"),
            "firstName":       w.get("firstName", ""),
            "lastName":        w.get("lastName", ""),
            "email":           w.get("email", ""),
            "phone":           w.get("phone") or w.get("contactNumber", ""),
            "dateOfBirth":     w.get("dateOfBirth", ""),
            "waiverId":        w.get("waiverId", ""),
            "signedAt":        w.get("signedAt") or w.get("createdDate") or w.get("createdAt", ""),
            "expiryDate":      w.get("expiryDate", ""),
            "isMinor":         bool(w.get("isForMinor")),
            "parentFirstName": "",
            "parentLastName":  "",
            "parentEmail":     "",
            "customFields":    w.get("customFields") or w.get("fields") or {},
        }
        parent_id = str(w.get("parentSignedWaiverId", ""))
        if parent_id and parent_id != "None":
            parent = id_map.get(parent_id, {})
            entry["parentFirstName"] = parent.get("firstName", "")
            entry["parentLastName"]  = parent.get("lastName", "")
            entry["parentEmail"]     = parent.get("email", "")
        enriched.append(entry)
    return jsonify({"total": len(enriched), "data": enriched})


# ─────────────────────────────────────────────────────────────────────────────
# API — misc
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/products")
@handle_errors
def get_products():
    if DEMO_MODE:
        return jsonify({"message": "Demo mode — connect Roller API for live products", "data": []})
    load_product_catalog()
    return jsonify({
        "total": len(_roster_cache["products_by_id"]),
        "data": [{"productId": pid, **info} for pid, info in _roster_cache["products_by_id"].items()],
    })


@app.route("/api/config")
def get_config():
    return jsonify({
        "mode":      "demo" if DEMO_MODE else "live",
        "pluFilter": MEMBERSHIP_PLUS,
    })


# Warm the cache in the background as soon as the process starts (works under
# both `python server.py` and gunicorn, since this runs at import time).
if not DEMO_MODE:
    threading.Thread(target=refresh_roster_cache, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = "DEMO MODE (no Roller API calls)" if DEMO_MODE else f"LIVE (Venue: {ROLLER_VENUE_ID})"
    print(f"\n🚣  Rowing Roster Data API — {mode}")
    print(f"    URL: http://localhost:{PORT}/api/members\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
