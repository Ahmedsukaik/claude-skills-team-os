"""The fictional brokerage and its CRM records. Every name, company, property and email here is
made up; emails use example.com. Dates are counted from "today", so the demo always looks current.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

FIRM = "Marrowby Commercial"
FIRM_LINE = "Marrowby Commercial (fictional brokerage)"

BROKERS: list[dict[str, str]] = [
    {"id": "B-1", "name": "Priya Natarajan", "email": "priya.natarajan@example.com"},
    {"id": "B-2", "name": "Sam Whitfield", "email": "sam.whitfield@example.com"},
    {"id": "B-3", "name": "Jordan Avery", "email": "jordan.avery@example.com"},
    {"id": "B-4", "name": "Alex Moreno", "email": "alex.moreno@example.com"},
]

STAGES = ["Lead", "Touring", "Proposal sent", "LOI signed", "Lease negotiation", "Closed won", "Closed lost"]
OPEN_STAGES = STAGES[:5]
STALE_DAYS = 21  # an open deal with no logged activity for this many days is stale

COMPANIES = [
    ("CO-1", "Quillon Logistics", "Third-party logistics"),
    ("CO-2", "Bramblecote Foods", "Food distribution"),
    ("CO-3", "Tessarine Biotech", "Life sciences"),
    ("CO-4", "Orchard Lane Dental Group", "Healthcare"),
    ("CO-5", "Kilnworth Brewing Co.", "Brewery"),
    ("CO-6", "Pellucid Software", "Software"),
]

CONTACTS = [  # id, first, last, job title, company
    ("C-1", "Dana", "Whitlock", "VP Real Estate", "CO-1"),
    ("C-2", "Celia", "Brandt", "CFO", "CO-1"),
    ("C-3", "Dana", "Okafor", "Operations Director", "CO-2"),
    ("C-4", "Lucia", "Ferrante", "Facilities Manager", "CO-2"),
    ("C-5", "Marcus", "Bell", "Head of Facilities", "CO-3"),
    ("C-6", "Ines", "Calder", "CFO", "CO-3"),
    ("C-7", "Ravi", "Menon", "Practice Owner", "CO-4"),
    ("C-8", "Theo", "Ashby", "Co-founder", "CO-5"),
    ("C-9", "Mara", "Quint", "Operations Lead", "CO-5"),
    ("C-10", "Hana", "Sato", "COO", "CO-6"),
    ("C-11", "Gil", "Navarro", "Office Manager", "CO-6"),
    ("C-12", "Owen", "Prescott", "Site Lead", "CO-1"),
]

PROPERTIES = [  # id, name, address, type, square feet
    ("P-1", "14 Elm Street Warehouse", "14 Elm Street", "Industrial", 42000),
    ("P-2", "220 Harbor Road Flex Space", "220 Harbor Road", "Flex / R&D", 18500),
    ("P-3", "9 Market Square, Suite 400", "9 Market Square", "Office", 6200),
    ("P-4", "75 Mill Pond Drive", "75 Mill Pond Drive", "Retail", 3100),
    ("P-5", "310 Canal Street Lab Building", "310 Canal Street", "Lab", 24000),
]

DEALS = [  # id, name, stage, owner, contact, company, property, days since the last activity
    ("D-1", "Quillon Logistics at 14 Elm Street", "Touring", "B-1", "C-1", "CO-1", "P-1", 4),
    ("D-2", "Bramblecote Foods at 220 Harbor Road", "Proposal sent", "B-2", "C-3", "CO-2", "P-2", 6),
    ("D-3", "Tessarine Biotech at 310 Canal Street", "Touring", "B-1", "C-5", "CO-3", "P-5", 9),
    ("D-4", "Orchard Lane Dental at 75 Mill Pond Drive", "LOI signed", "B-3", "C-7", "CO-4", "P-4", 2),
    ("D-5", "Kilnworth Brewing at 14 Elm Street", "Lead", "B-4", "C-8", "CO-5", "P-1", 38),
    ("D-6", "Pellucid Software at 9 Market Square", "Lease negotiation", "B-4", "C-10", "CO-6", "P-3", 25),
    ("D-7", "Quillon Logistics at 220 Harbor Road", "Closed lost", "B-2", "C-12", "CO-1", "P-2", 60),
    ("D-8", "Tessarine Biotech at 9 Market Square", "Closed won", "B-3", "C-6", "CO-3", "P-3", 45),
]

NOTES = [  # id, contact, deal, property, days ago, author, summary, discussed
    ("N-1", "C-1", "D-1", "P-1", 4, "B-1", "First tour of 14 Elm Street with Dana Whitlock",
     ["Needs at least 30 dock doors", "Wants a 5 year term with one renewal option"]),
    ("N-2", "C-3", "D-2", "P-2", 6, "B-2", "Proposal for 220 Harbor Road sent to Dana Okafor",
     ["Proposal at $14.50 per square foot, 7 year term", "Dana is checking cold storage power with her team"]),
    ("N-3", "C-5", "D-3", "P-5", 9, "B-1", "Intro call with Marcus Bell about lab space",
     ["Tessarine needs about 20,000 square feet of lab and office", "Freezer farm needs backup power"]),
    ("N-4", "C-7", "D-4", "P-4", 2, "B-3", "LOI signed for 75 Mill Pond Drive",
     ["Ravi signed the LOI", "Build out allowance still to agree"]),
    ("N-5", "C-10", "D-6", "P-3", 25, "B-4", "Lease redlines from Pellucid's counsel",
     ["Pushing back on the tenant improvement allowance"]),
]

TASKS = [  # id, title, contact, deal, due (days from today), author
    ("T-1", "Send Dana Whitlock the dock door count for 14 Elm Street", "C-1", "D-1", 2, "B-1"),
    ("T-2", "Check back with Theo Ashby about timing", "C-8", "D-5", -20, "B-4"),
]

EVENTS = [  # id, title, days from today, start time, minutes, broker, contacts, property
    ("E-1", "Second tour: 14 Elm Street with Dana Whitlock", 1, time(10, 0), 60, "B-1", ["C-1", "C-12"], "P-1"),
    ("E-2", "Lease review call with Hana Sato", 2, time(9, 30), 45, "B-4", ["C-10"], "P-3"),
    ("E-3", "Call: Tessarine lab requirements with Marcus Bell", 3, time(14, 0), 30, "B-1", ["C-5"], "P-5"),
    ("E-4", "Site visit: 220 Harbor Road with Dana Okafor and Lucia Ferrante", 5, time(11, 0), 90, "B-2",
     ["C-3", "C-4"], "P-2"),
]


def _stamp(day: date, hour: int = 16) -> str:
    """A recorded_at for seeded history: a fixed time of day, in UTC."""
    return datetime.combine(day, time(hour, 0), tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def broker(broker_id: str) -> dict[str, str]:
    return next((b for b in BROKERS if b["id"] == broker_id), BROKERS[0])


def seed(today: date) -> dict[str, dict[str, dict[str, Any]]]:
    """A fresh copy of the CRM's records, dated from `today`."""
    names = {b["id"]: b["name"] for b in BROKERS}
    companies = {cid: {"id": cid, "name": name, "industry": industry, "recorded_at": _stamp(today - timedelta(days=200))}
                 for cid, name, industry in COMPANIES}
    contacts = {cid: {"id": cid, "first_name": first, "last_name": last, "name": f"{first} {last}",
                      "email": f"{first}.{last}@example.com".lower(), "job_title": title, "company_id": co,
                      "recorded_at": _stamp(today - timedelta(days=120))}
                for cid, first, last, title, co in CONTACTS}
    properties = {pid: {"id": pid, "name": name, "address": address, "type": kind, "square_feet": size}
                  for pid, name, address, kind, size in PROPERTIES}
    deals = {did: {"id": did, "name": name, "stage": stage, "owner": names[owner], "contact_id": contact, "company_id": co,
                   "property_id": prop, "last_activity": (today - timedelta(days=ago)).isoformat(),
                   "recorded_at": _stamp(today - timedelta(days=90))}
             for did, name, stage, owner, contact, co, prop, ago in DEALS}
    notes = {nid: {"id": nid, "contact_id": contact, "company_id": contacts[contact]["company_id"], "deal_id": deal,
                   "property_id": prop, "summary": summary, "discussed": discussed, "next_steps": [],
                   "stated_time_text": None, "stated_time": None, "stated_time_note": None,
                   "recorded_at": _stamp(today - timedelta(days=ago)), "logged_by": names[author]}
             for nid, contact, deal, prop, ago, author, summary, discussed in NOTES}
    tasks = {tid: {"id": tid, "title": title, "contact_id": contact, "deal_id": deal, "status": "open",
                   "due_text": None, "due": (today + timedelta(days=due)).isoformat(), "due_note": None,
                   "recorded_at": _stamp(today - timedelta(days=7)), "logged_by": names[author]}
             for tid, title, contact, deal, due, author in TASKS}
    events = {eid: {"id": eid, "title": title, "start": datetime.combine(today + timedelta(days=days), start).isoformat(
                        timespec="minutes"), "minutes": minutes, "broker": names[who], "contact_ids": people, "property_id": prop}
              for eid, title, days, start, minutes, who, people, prop in EVENTS}
    return {"companies": companies, "contacts": contacts, "properties": properties, "deals": deals, "notes": notes,
            "tasks": tasks, "events": events}
