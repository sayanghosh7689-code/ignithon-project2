"""
views.py — Streamlit views for ServeSmart (login, student, technician, admin).
"""

import streamlit as st
import models as m


def login_view():
    st.title("🛠️ ServeSmart")
    st.caption("Campus Service Ticket System — log in with your account and password.")

    role = st.radio("I am a:", ["Student", "Technician", "Admin"], horizontal=True)
    options = {"Student": m.STUDENTS, "Technician": m.TECHS, "Admin": m.ADMINS}[role]

    user_id = st.selectbox("Choose account", list(options.keys()), format_func=lambda k: f"{options[k]} ({k})")
    password = st.text_input("Password", type="password", help=f"Demo password for every account: {m.DEFAULT_PASSWORD}")

    if st.button("Log in", type="primary"):
        user = m.verify_login(user_id, password)
        if user:
            st.session_state.user = user
            st.rerun()
        else:
            st.error("Incorrect password.")


def render_ticket_card(t, actor_id, actor_role, allow_advance=False):
    tech_name = m.name_for(t["technicianId"]) if t["technicianId"] else "Unassigned"
    header = f"{t['status']} · {t['priority']} · {t['title']}"
    with st.expander(header):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**Ticket ID:** {t['id']}")
            st.write(f"**Category:** {t['category']}")
            st.write(f"**Location:** {t['location']}")
        with c2:
            st.write(f"**Student:** {m.name_for(t['studentId'])}")
            st.write(f"**Technician:** {tech_name}")
            st.write(f"**Created:** {t['createdAt']}")
        st.write("**Description:**")
        st.write(t["description"])

        st.write("**Status history:**")
        for entry in t["activity"]:
            st.write(f"- {entry['at']} — {entry['status']} (by {m.name_for(entry['by'])})")

        if allow_advance:
            nxt = m.next_status(t["status"])
            if nxt:
                if st.button(f"Advance to '{nxt}'", key=f"advance_{t['id']}"):
                    ok, msg = m.advance_status(t["id"], nxt, actor_id, actor_role)
                    (st.success if ok else st.error)(msg)
                    st.rerun()
            else:
                st.info("This ticket is already Closed — no further transitions.")


def student_view(user):
    st.title(f"🎓 Welcome, {user['name']}")
    tab_list, tab_new = st.tabs(["My Tickets", "New Ticket"])

    with tab_list:
        my_tickets = [t for t in m.get_all_tickets() if t["studentId"] == user["id"]]
        search = st.text_input("Search by title", "")
        if search.strip():
            my_tickets = [t for t in my_tickets if search.strip().lower() in t["title"].lower()]

        if not my_tickets:
            st.info("You haven't raised any tickets yet.")
        else:
            st.caption(f"{len(my_tickets)} ticket(s)")
            for t in my_tickets:
                render_ticket_card(t, user["id"], user["role"])

    with tab_new:
        st.subheader("Raise a new ticket")
        title = st.text_input("Title", key="new_title")
        description = st.text_area("Description", key="new_desc")
        # Live feedback as the user types, instead of only after submit.
        desc_len = len(description.strip())
        st.caption(f"{desc_len} / 20 characters minimum" + (" ✅" if desc_len >= 20 else ""))
        category = st.selectbox("Category", m.CATEGORIES, key="new_cat")
        location = st.text_input("Location", key="new_loc")
        priority = st.selectbox("Priority", m.PRIORITY_ORDER, key="new_pri")

        if st.button("Submit ticket", type="primary"):
            ok, errors, ticket = m.create_ticket(title, description, category, location, priority, user["id"])
            if ok:
                st.success(f"Ticket {ticket['id']} created with status Open. It now appears under My Tickets.")
                for k in ("new_title", "new_desc", "new_loc"):
                    st.session_state[k] = ""
                st.rerun()
            else:
                for e in errors:
                    st.error(e)


def technician_view(user):
    st.title(f"🔧 Technician Dashboard — {user['name']}")

    assigned = [t for t in m.get_all_tickets() if t["technicianId"] == user["id"]]

    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.multiselect("Filter by status", m.STATUS_ORDER, default=[])
    with col2:
        priority_filter = st.multiselect("Filter by priority", m.PRIORITY_ORDER, default=[])

    filtered = assigned
    if status_filter:
        filtered = [t for t in filtered if t["status"] in status_filter]
    if priority_filter:
        filtered = [t for t in filtered if t["priority"] in priority_filter]
    filtered = sorted(filtered, key=m.priority_sort_key)

    st.caption(f"{len(filtered)} of {len(assigned)} assigned ticket(s) shown")

    if not filtered:
        st.info("No tickets match the current filters.")
    else:
        for t in filtered:
            render_ticket_card(t, user["id"], user["role"], allow_advance=True)


def admin_view(user):
    st.title(f"🗂️ Admin — {user['name']}")

    tab_unassigned, tab_all = st.tabs(["Unassigned Tickets", "All Tickets (Reassign)"])
    all_tickets = m.get_all_tickets()

    with tab_unassigned:
        unassigned = sorted([t for t in all_tickets if t["technicianId"] is None], key=m.priority_sort_key)
        st.caption(f"{len(unassigned)} unassigned ticket(s)")
        for t in unassigned:
            with st.expander(f"{t['priority']} · {t['title']} · {t['location']}"):
                st.write(t["description"])
                tech_pick = st.selectbox(
                    "Assign to technician", list(m.TECHS.keys()),
                    format_func=lambda k: m.TECHS[k], key=f"assign_{t['id']}"
                )
                if st.button("Assign", key=f"assign_btn_{t['id']}"):
                    ok, msg = m.assign_ticket(t["id"], tech_pick, user["id"], user["role"])
                    (st.success if ok else st.error)(msg)
                    st.rerun()

    with tab_all:
        st.caption(f"{len(all_tickets)} total ticket(s)")
        for t in sorted(all_tickets, key=m.priority_sort_key):
            tech_name = m.name_for(t["technicianId"]) if t["technicianId"] else "Unassigned"
            header = f"{t['status']} · {t['title']} · {t['priority']} · Tech: {tech_name}"
            with st.expander(header):
                st.write(t["description"])
                tech_ids = list(m.TECHS.keys())
                default_idx = tech_ids.index(t["technicianId"]) if t["technicianId"] in tech_ids else 0
                new_tech = st.selectbox(
                    "Reassign to", tech_ids, index=default_idx,
                    format_func=lambda k: m.TECHS[k], key=f"reassign_{t['id']}"
                )
                if st.button("Reassign", key=f"reassign_btn_{t['id']}"):
                    ok, msg = m.assign_ticket(t["id"], new_tech, user["id"], user["role"])
                    (st.success if ok else st.error)(msg)
                    st.rerun()
                st.write("**Status history:**")
                for entry in t["activity"]:
                    st.write(f"- {entry['at']} — {entry['status']} (by {m.name_for(entry['by'])})")
