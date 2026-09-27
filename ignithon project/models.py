"""
models.py — data layer and business rules for ServeSmart.

Persistence: SQLite (servesmart.db, created next to this file), so data
survives a server restart — no more in-memory-only store.

Auth: simple hashed-password check against a users table (seeded with a
shared demo password; see DEFAULT_PASSWORD below).

Concurrency: a module-level lock serializes writes so two Streamlit
sessions in the same process can't corrupt a ticket at the same time.
This protects a single-process deployment; it is NOT a substitute for a
real backend (e.g. FastAPI + Postgres) if you need multiple server
processes or high concurrent write volume.
"""

import sqlite3
import hashlib
import threading
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "servesmart.db"
_write_lock = threading.Lock()

STATUS_ORDER = ["Open", "Assigned", "In Progress", "Resolved", "Closed"]
PRIORITY_ORDER = ["P1", "P2", "P3", "P4"]
CATEGORIES = ["Electrical", "Plumbing", "HVAC", "Furniture", "IT", "Cleaning", "Other"]

DEFAULT_PASSWORD = "demo123"  # seeded for every demo account; change per-user via set_password()

STUDENTS = {
    "stu1": "Ava Patel", "stu2": "Liam Chen", "stu3": "Maya Singh",
    "stu4": "Noah Kim", "stu5": "Zoe Rivera", "stu6": "Ethan Wood",
    "stu7": "Priya Nair", "stu8": "Omar Ali", "stu9": "Grace Lin",
    "stu10": "Jack Ford",
}
TECHS = {"tech1": "Sam Torres", "tech2": "Dana Brooks", "tech3": "Ravi Desai"}
ADMINS = {"admin1": "Chris Park"}

ALL_USERS = {
    **{k: ("Student", v) for k, v in STUDENTS.items()},
    **{k: ("Technician", v) for k, v in TECHS.items()},
    **{k: ("Admin", v) for k, v in ADMINS.items()},
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def new_ticket_id():
    return "T" + uuid.uuid4().hex[:6].upper()


def name_for(user_id):
    return ALL_USERS[user_id][1] if user_id in ALL_USERS else user_id


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ------------------------------------------------------------ schema/seed --

def init_db():
    conn = get_conn()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                location TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                studentId TEXT NOT NULL,
                technicianId TEXT,
                createdAt TEXT NOT NULL,
                updatedAt TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL REFERENCES tickets(id),
                status TEXT NOT NULL,
                at TEXT NOT NULL,
                by TEXT NOT NULL
            )
        """)
    _seed_if_empty(conn)
    conn.close()


def _seed_if_empty(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        with conn:
            for uid, (role, name) in ALL_USERS.items():
                conn.execute(
                    "INSERT INTO users (id, name, role, password_hash) VALUES (?, ?, ?, ?)",
                    (uid, name, role, hash_password(DEFAULT_PASSWORD)),
                )

    if conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
        seed = [
            ("Flickering lights in room 204", "The overhead lights in room 204 flicker constantly and buzz.",
             "Electrical", "Building A, Room 204", "P2", "stu1", "Assigned", "tech1"),
            ("Leaking faucet in dorm bathroom", "Faucet in the 3rd floor bathroom leaks continuously.",
             "Plumbing", "Dorm C, 3rd Floor Bathroom", "P3", "stu2", "Open", None),
            ("No AC in lecture hall", "AC unit not cooling, room is very hot during afternoon classes.",
             "HVAC", "Building B, Lecture Hall 1", "P1", "stu3", "In Progress", "tech2"),
            ("Broken chair in library", "One of the study chairs on the 2nd floor has a broken leg.",
             "Furniture", "Library, 2nd Floor", "P4", "stu4", "Open", None),
            ("Projector not turning on", "The projector in room 110 won't power on at all.",
             "IT", "Building A, Room 110", "P2", "stu5", "Open", None),
        ]
        with _write_lock, conn:
            for title, desc, cat, loc, pri, sid, status, tech in seed:
                tid = new_ticket_id()
                ts = now_iso()
                conn.execute(
                    """INSERT INTO tickets
                       (id, title, description, category, location, priority, status,
                        studentId, technicianId, createdAt, updatedAt)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tid, title, desc, cat, loc, pri, status, sid, tech, ts, ts),
                )
                conn.execute(
                    "INSERT INTO activity (ticket_id, status, at, by) VALUES (?, ?, ?, ?)",
                    (tid, status, ts, sid),
                )


# ---------------------------------------------------------------------auth--

def verify_login(user_id, password):
    """Returns the user dict on success, or None on bad id/password."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None or row["password_hash"] != hash_password(password):
        return None
    return {"id": row["id"], "name": row["name"], "role": row["role"]}


def set_password(user_id, new_password):
    with _write_lock:
        conn = get_conn()
        with conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(new_password), user_id),
            )
        conn.close()


# ------------------------------------------------------------------tickets--

def _row_to_ticket(conn, row):
    activity = conn.execute(
        "SELECT status, at, by FROM activity WHERE ticket_id = ? ORDER BY id", (row["id"],)
    ).fetchall()
    t = dict(row)
    t["activity"] = [dict(a) for a in activity]
    return t


def get_all_tickets():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tickets ORDER BY createdAt DESC").fetchall()
    tickets = [_row_to_ticket(conn, r) for r in rows]
    conn.close()
    return tickets


def get_ticket(ticket_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    t = _row_to_ticket(conn, row) if row else None
    conn.close()
    return t


def priority_sort_key(ticket):
    """Sorts P1..P4 correctly instead of as plain text (the original bug)."""
    return PRIORITY_ORDER.index(ticket["priority"]) if ticket["priority"] in PRIORITY_ORDER else len(PRIORITY_ORDER)


def next_status(current):
    idx = STATUS_ORDER.index(current)
    return STATUS_ORDER[idx + 1] if idx + 1 < len(STATUS_ORDER) else None


def can_transition(current, target):
    """Only the immediate next status in the sequence is a valid transition."""
    if current not in STATUS_ORDER or target not in STATUS_ORDER:
        return False
    return STATUS_ORDER.index(target) == STATUS_ORDER.index(current) + 1


def validate_new_ticket(title, description, category, location, priority):
    errors = []
    if not title.strip():
        errors.append("Title is required.")
    if not description.strip():
        errors.append("Description is required.")
    elif len(description.strip()) < 20:
        errors.append(f"Description must be at least 20 characters (currently {len(description.strip())}).")
    if not category:
        errors.append("Category is required.")
    if not location.strip():
        errors.append("Location is required.")
    if priority not in PRIORITY_ORDER:
        errors.append("Priority must be one of P1, P2, P3, P4.")
    return errors


def create_ticket(title, description, category, location, priority, student_id):
    errors = validate_new_ticket(title, description, category, location, priority)
    if errors:
        return False, errors, None

    tid = new_ticket_id()
    ts = now_iso()
    with _write_lock:
        conn = get_conn()
        with conn:
            conn.execute(
                """INSERT INTO tickets
                   (id, title, description, category, location, priority, status,
                    studentId, technicianId, createdAt, updatedAt)
                   VALUES (?, ?, ?, ?, ?, ?, 'Open', ?, NULL, ?, ?)""",
                (tid, title.strip(), description.strip(), category, location.strip(),
                 priority, student_id, ts, ts),
            )
            conn.execute(
                "INSERT INTO activity (ticket_id, status, at, by) VALUES (?, 'Open', ?, ?)",
                (tid, ts, student_id),
            )
        conn.close()
    return True, [], get_ticket(tid)


def advance_status(ticket_id, target_status, actor_id, actor_role):
    """Server-side enforced transition with role/ownership checks baked in."""
    ticket = get_ticket(ticket_id)
    if ticket is None:
        return False, "Ticket not found."
    if actor_role == "Technician" and ticket["technicianId"] != actor_id:
        return False, "You can only update tickets assigned to you."
    if actor_role not in ("Technician", "Admin"):
        return False, "You are not allowed to update ticket status."
    if not can_transition(ticket["status"], target_status):
        return False, f"Cannot move from {ticket['status']} to {target_status}."

    ts = now_iso()
    with _write_lock:
        conn = get_conn()
        with conn:
            conn.execute(
                "UPDATE tickets SET status = ?, updatedAt = ? WHERE id = ?",
                (target_status, ts, ticket_id),
            )
            conn.execute(
                "INSERT INTO activity (ticket_id, status, at, by) VALUES (?, ?, ?, ?)",
                (ticket_id, target_status, ts, actor_id),
            )
        conn.close()
    return True, "Status updated."


def assign_ticket(ticket_id, technician_id, actor_id, actor_role):
    if actor_role != "Admin":
        return False, "Only admins can assign tickets."
    ticket = get_ticket(ticket_id)
    if ticket is None:
        return False, "Ticket not found."

    ts = now_iso()
    new_status = "Assigned" if ticket["status"] == "Open" else ticket["status"]
    log_label = new_status if ticket["status"] == "Open" else f"{ticket['status']} (reassigned)"

    with _write_lock:
        conn = get_conn()
        with conn:
            conn.execute(
                "UPDATE tickets SET technicianId = ?, status = ?, updatedAt = ? WHERE id = ?",
                (technician_id, new_status, ts, ticket_id),
            )
            conn.execute(
                "INSERT INTO activity (ticket_id, status, at, by) VALUES (?, ?, ?, ?)",
                (ticket_id, log_label, ts, actor_id),
            )
        conn.close()
    return True, "Ticket assigned."
