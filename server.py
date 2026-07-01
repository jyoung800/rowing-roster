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
import requests
from datetime import datetime, timezone, date
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

PLU_FIELD_CANDIDATES = ("plu", "productCode", "sku", "productPlu", "externalId", "barcode")

ROLLER_TOKEN_URL = "https://api.roller.app/token"
ROLLER_DATA_API  = "https://api.roller.app"

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
    if schedule is None:
        return (roller_status or "").lower(), None
    return ("active" if schedule["active"] else "inactive"), schedule["window"]


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


def roller_get(path: str, params: dict | None = None) -> dict:
    token = get_access_token()
    for attempt in range(2):
        resp = requests.get(
            f"{ROLLER_DATA_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=15,
        )
        if resp.status_code == 401 and attempt == 0:
            _token_cache["token"] = None
            token = get_access_token()
            continue
        resp.raise_for_status()
        return resp.json()
    return {}


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
            return jsonify({"error": str(e), "status": code}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# API — health
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status":      "ok",
        "mode":        "demo" if DEMO_MODE else "live",
        "venue_id":    ROLLER_VENUE_ID or "(demo)",
        "plu_filter":  MEMBERSHIP_PLUS,
        "plu_count":   len(MEMBERSHIP_PLUS),
    })


# ─────────────────────────────────────────────────────────────────────────────
# API — summary
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/summary")
@handle_errors
def get_summary():
    today = datetime.now(timezone.utc).date()

    if DEMO_MODE:
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

    membership_data = roller_get("/data/membershipstatuses", {"venueId": ROLLER_VENUE_ID, "pageSize": 500})
    memberships = membership_data.get("data", [])
    if MEMBERSHIP_PLUS:
        memberships = [m for m in memberships if any(str(m.get(f,"")) in MEMBERSHIP_PLUS for f in PLU_FIELD_CANDIDATES)]

    active = sum(
        1 for m in memberships
        if resolve_status(m.get("membershipName"), m.get("startDate"), m.get("status",""), today)[0] == "active"
    )
    waiver_data  = roller_get("/data/signedwaivers", {"venueId": ROLLER_VENUE_ID, "pageSize": 1})
    return jsonify({
        "activeMembers":   active,
        "inactiveMembers": len(memberships) - active,
        "totalMembers":    len(memberships),
        "signedWaivers":   waiver_data.get("total", 0),
        "asOf":            datetime.now(timezone.utc).isoformat(),
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
        if status_filter != "all":
            roster = [m for m in roster if m["status"] == status_filter]
        if search:
            roster = [m for m in roster if search in m["fullName"].lower() or search in m["email"].lower()]
        roster = sorted(roster, key=lambda x: (x["lastName"].lower(), x["firstName"].lower()))
        return jsonify({"total": len(roster), "status": status_filter, "data": roster})

    # Live mode
    membership_data = roller_get("/data/membershipstatuses", {"venueId": ROLLER_VENUE_ID, "pageSize": 500})
    memberships     = membership_data.get("data", [])
    if MEMBERSHIP_PLUS:
        memberships = [m for m in memberships if any(str(m.get(f,"")) in MEMBERSHIP_PLUS for f in PLU_FIELD_CANDIDATES)]

    customer_data = roller_get("/data/customers", {"venueId": ROLLER_VENUE_ID, "pageSize": 500})
    customer_map  = {str(c["customerId"]): c for c in customer_data.get("data", [])}

    roster = []
    for m in memberships:
        cid      = str(m.get("customerId",""))
        customer = customer_map.get(cid, {})
        first    = customer.get("firstName","")
        last     = customer.get("lastName","")
        full_name = f"{first} {last}".strip() or f"Member {cid}"
        if search and search not in full_name.lower() and search not in customer.get("email","").lower():
            continue
        effective_status, window = resolve_status(m.get("membershipName"), m.get("startDate"), m.get("status",""), today)
        roster.append({
            "memberId":        cid,
            "firstName":       first,
            "lastName":        last,
            "fullName":        full_name,
            "email":           customer.get("email",""),
            "phone":           customer.get("phone",""),
            "dateOfBirth":     customer.get("dateOfBirth",""),
            "membershipName":  m.get("membershipName",""),
            "membershipType":  m.get("membershipType",""),
            "status":          effective_status,
            "rollerStatus":    m.get("status",""),
            "scheduleWindow":  window,
            "startDate":       m.get("startDate",""),
            "endDate":         m.get("endDate",""),
            "nextBillingDate": m.get("nextBillingDate",""),
            "plu":             next((str(m.get(f)) for f in PLU_FIELD_CANDIDATES if m.get(f)), ""),
            "hasWaiver":       False,
            "waiverDate":      None,
        })

    if status_filter != "all":
        roster = [m for m in roster if m["status"] == status_filter]

    try:
        waiver_data = roller_get("/data/signedwaivers", {"venueId": ROLLER_VENUE_ID, "pageSize": 1000})
        waiver_map  = {}
        for w in waiver_data.get("data", []):
            cid_w = str(w.get("customerId",""))
            date  = w.get("signedAt") or w.get("createdAt") or ""
            if cid_w not in waiver_map or date > waiver_map[cid_w]:
                waiver_map[cid_w] = date
        for entry in roster:
            if entry["memberId"] in waiver_map:
                entry["hasWaiver"]  = True
                entry["waiverDate"] = waiver_map[entry["memberId"]]
    except Exception:
        pass

    roster.sort(key=lambda x: (x["lastName"].lower(), x["firstName"].lower()))
    return jsonify({"total": len(roster), "status": status_filter, "data": roster})


# ─────────────────────────────────────────────────────────────────────────────
# API — waivers
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/waivers")
@handle_errors
def get_waivers():
    if DEMO_MODE:
        return jsonify({"total": len(DEMO_WAIVERS_DATA), "data": DEMO_WAIVERS_DATA})

    data     = roller_get("/data/signedwaivers", {"venueId": ROLLER_VENUE_ID, "pageSize": 500})
    waivers  = data.get("data", [])
    id_map   = {str(w.get("signedWaiverId", w.get("id",""))): w for w in waivers}
    enriched = []
    for w in waivers:
        entry = {
            "signedWaiverId":  w.get("signedWaiverId") or w.get("id"),
            "customerId":      w.get("customerId"),
            "firstName":       w.get("firstName",""),
            "lastName":        w.get("lastName",""),
            "email":           w.get("email",""),
            "phone":           w.get("phone",""),
            "dateOfBirth":     w.get("dateOfBirth",""),
            "waiverName":      w.get("waiverName") or w.get("name",""),
            "signedAt":        w.get("signedAt") or w.get("createdAt",""),
            "isMinor":         False,
            "parentFirstName": "",
            "parentLastName":  "",
            "parentEmail":     "",
            "customFields":    w.get("customFields") or w.get("fields") or {},
        }
        parent_id = str(w.get("parentSignedWaiverId",""))
        if parent_id and parent_id != "None":
            entry["isMinor"] = True
            parent = id_map.get(parent_id, {})
            entry["parentFirstName"] = parent.get("firstName","")
            entry["parentLastName"]  = parent.get("lastName","")
            entry["parentEmail"]     = parent.get("email","")
        enriched.append(entry)
    return jsonify({"total": len(enriched), "data": enriched})


# ─────────────────────────────────────────────────────────────────────────────
# API — misc (live only)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/products")
@handle_errors
def get_products():
    if DEMO_MODE:
        return jsonify({"message": "Demo mode — connect Roller API for live products", "data": []})
    return jsonify(roller_get("/data/products", {"venueId": ROLLER_VENUE_ID, "pageSize": 500}))


@app.route("/api/waiver-forms")
@handle_errors
def get_waiver_forms():
    if DEMO_MODE:
        return jsonify({"message": "Demo mode", "data": []})
    return jsonify(roller_get("/data/waivers", {"venueId": ROLLER_VENUE_ID}))


@app.route("/api/membership-redemptions")
@handle_errors
def get_redemptions():
    if DEMO_MODE:
        return jsonify({"message": "Demo mode", "data": []})
    params = {"venueId": ROLLER_VENUE_ID, "pageSize": 500}
    since  = request.args.get("since","")
    if since:
        params["modifiedSince"] = since
    return jsonify(roller_get("/data/membershipredemptions", params))


@app.route("/api/config")
def get_config():
    return jsonify({
        "mode":      "demo" if DEMO_MODE else "live",
        "pluFilter": MEMBERSHIP_PLUS,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = "DEMO MODE (no Roller API calls)" if DEMO_MODE else f"LIVE (Venue: {ROLLER_VENUE_ID})"
    print(f"\n🚣  Rowing Roster Data API — {mode}")
    print(f"    URL: http://localhost:{PORT}/api/members\n")
    app.run(host="0.0.0.0", port=PORT, debug=False)
