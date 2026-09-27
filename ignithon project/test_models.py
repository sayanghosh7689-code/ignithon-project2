"""
tests/test_models.py — unit tests for ServeSmart's core business rules.

Run from the project root with:
    pytest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models as m


def test_can_transition_sequential_ok():
    assert m.can_transition("Open", "Assigned")
    assert m.can_transition("Assigned", "In Progress")
    assert m.can_transition("In Progress", "Resolved")
    assert m.can_transition("Resolved", "Closed")


def test_can_transition_rejects_skips_and_backwards():
    assert not m.can_transition("Open", "In Progress")  # skip
    assert not m.can_transition("Closed", "Open")        # backwards / wrap
    assert not m.can_transition("Assigned", "Open")      # backwards
    assert not m.can_transition("Closed", "Closed")      # no-op


def test_priority_sort_key_orders_p1_first():
    tickets = [{"priority": "P3"}, {"priority": "P1"}, {"priority": "P4"}, {"priority": "P2"}]
    ordered = sorted(tickets, key=m.priority_sort_key)
    assert [t["priority"] for t in ordered] == ["P1", "P2", "P3", "P4"]


def test_validate_new_ticket_requires_all_fields():
    errors = m.validate_new_ticket("", "", "", "", "")
    assert len(errors) >= 4


def test_validate_new_ticket_enforces_min_description_length():
    errors = m.validate_new_ticket("Title", "too short", "IT", "Room 1", "P1")
    assert any("20 characters" in e for e in errors)


def test_validate_new_ticket_rejects_bad_priority():
    errors = m.validate_new_ticket(
        "Title", "A description that is definitely long enough.", "IT", "Room 1", "P9"
    )
    assert any("P1, P2, P3, P4" in e for e in errors)


def test_validate_new_ticket_passes_with_valid_data():
    errors = m.validate_new_ticket(
        "Broken window", "The window in room 12 will not close properly.", "Other", "Room 12", "P2"
    )
    assert errors == []


def test_create_ticket_and_advance_status_end_to_end(tmp_path, monkeypatch):
    # Point at a throwaway DB so tests never touch servesmart.db.
    monkeypatch.setattr(m, "DB_PATH", tmp_path / "test.db")
    m.init_db()

    ok, errors, ticket = m.create_ticket(
        "Test ticket", "A sufficiently long description for testing purposes.",
        "IT", "Test Room", "P1", "stu1",
    )
    assert ok and not errors
    assert ticket["status"] == "Open"

    ok, _ = m.assign_ticket(ticket["id"], "tech1", "admin1", "Admin")
    assert ok
    ticket = m.get_ticket(ticket["id"])
    assert ticket["status"] == "Assigned"
    assert ticket["technicianId"] == "tech1"

    ok, _ = m.advance_status(ticket["id"], "In Progress", "tech1", "Technician")
    assert ok
    ticket = m.get_ticket(ticket["id"])
    assert ticket["status"] == "In Progress"

    # A technician who isn't assigned to the ticket cannot advance it.
    ok, msg = m.advance_status(ticket["id"], "Resolved", "tech2", "Technician")
    assert not ok
    assert "assigned to you" in msg

    # Skipping a status is rejected even for the correct technician.
    ok, msg = m.advance_status(ticket["id"], "Closed", "tech1", "Technician")
    assert not ok
    assert "Cannot move" in msg


def test_assign_ticket_requires_admin_role():
    ok, msg = m.assign_ticket("T000000", "tech1", "stu1", "Student")
    assert not ok
    assert "Only admins" in msg
