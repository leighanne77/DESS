"""Events catalog — catalog numbers and the Invited/Attended tie."""

from typing import Callable

from sqlalchemy.orm import Session

from app.models import Contact, User
from app.services.tool_dispatch import dispatch_tool_call


def _make_event(db: Session, user: User, **kw) -> dict:
    params = {"title": "Mobile Harbor Dinner", **kw}
    return dispatch_tool_call("create_event", params, user, db)


def test_create_event_assigns_catalog_numbers_per_year(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    first = _make_event(db, user, event_date="2026-09-01")
    second = _make_event(db, user, title="Demo Day", event_date="2026-10-01")
    other_year = _make_event(db, user, title="Kickoff", event_date="2027-01-15")
    assert first["created_event"]["catalog_number"] == "DIN-2026-001"
    assert second["created_event"]["catalog_number"] == "DIN-2026-002"
    assert other_year["created_event"]["catalog_number"] == "DIN-2027-001"


def test_invite_then_attend_upgrades_never_downgrades(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    event = _make_event(db, user)["created_event"]
    contact = Contact(name="Jane Prospect", owner_id=user.id, is_private=False)
    db.add(contact)
    db.commit()

    r = dispatch_tool_call(
        "record_event_invite",
        {"event": event["catalog_number"], "contact_id": contact.id},
        user,
        db,
    )
    assert r["status"] == "Invited"

    r = dispatch_tool_call(
        "record_event_invite",
        {
            "event": event["catalog_number"],
            "contact_id": contact.id,
            "status": "Attended",
        },
        user,
        db,
    )
    assert r["status"] == "Attended"

    # Re-recording an invite after attendance never downgrades.
    r = dispatch_tool_call(
        "record_event_invite",
        {"event": event["catalog_number"], "contact_id": contact.id},
        user,
        db,
    )
    assert r["status"] == "Attended"


def test_search_by_event_and_status(
    db: Session, user_factory: Callable[..., User]
) -> None:
    """'Who attended X' vs 'invited but did not come' — and privacy: a
    private contact's event tie is invisible to a teammate who can't see
    the contact."""
    owner = user_factory()
    other = user_factory(email="other2@fundslccllc.com")
    event = _make_event(db, owner)["created_event"]

    came = Contact(name="Came Along", owner_id=owner.id, is_private=False)
    no_show = Contact(name="No Show", owner_id=owner.id, is_private=False)
    secret = Contact(name="Secret Guest", owner_id=owner.id, is_private=True)
    db.add_all([came, no_show, secret])
    db.commit()

    for contact, status in [
        (came, "Attended"),
        (no_show, "Invited"),
        (secret, "Attended"),
    ]:
        dispatch_tool_call(
            "record_event_invite",
            {
                "event": event["catalog_number"],
                "contact_id": contact.id,
                "status": status,
            },
            owner,
            db,
        )

    def names(user, **extra):
        r = dispatch_tool_call(
            "search_contacts",
            {"event": event["catalog_number"], **extra},
            user,
            db,
        )
        assert r.get("event", {}).get("catalog_number") == event["catalog_number"]
        return {c["name"] for c in r["results"]}

    assert names(owner) == {"Came Along", "No Show", "Secret Guest"}
    assert names(owner, event_status="Attended") == {"Came Along", "Secret Guest"}
    assert names(owner, event_status="Invited") == {"No Show"}
    # The other teammate never sees the private guest.
    assert "Secret Guest" not in names(other)

    # And list_events reports the counts.
    listed = dispatch_tool_call("list_events", {}, owner, db)
    row = next(
        e for e in listed["events"] if e["catalog_number"] == event["catalog_number"]
    )
    assert row["invited_count"] == 3
    assert row["attended_count"] == 2


def test_card_event_endpoints_list_and_annotate(client, db, user_factory) -> None:
    """GET/POST /contacts/{id}/events — the card surface: history with
    notes, forward-only status, 404 on invisible contacts."""
    from app.security import create_access_token

    user = user_factory()
    headers = {"Authorization": f"Bearer {create_access_token(user_id=user.id)}"}
    event = _make_event(db, user, title="Card Test Briefing")["created_event"]
    contact = Contact(name="Card Person", owner_id=user.id, is_private=False)
    db.add(contact)
    db.commit()

    r = client.post(
        f"/api/contacts/{contact.id}/events",
        json={"event": event["catalog_number"], "note": "asked for the deck"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "Invited"
    assert r.json()["note"] == "asked for the deck"

    # Upgrade + note preserved when not resent.
    r = client.post(
        f"/api/contacts/{contact.id}/events",
        json={"event": event["catalog_number"], "status": "Attended"},
        headers=headers,
    )
    assert r.json()["status"] == "Attended"
    assert r.json()["note"] == "asked for the deck"

    r = client.get(f"/api/contacts/{contact.id}/events", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["catalog_number"] == event["catalog_number"]
    assert rows[0]["status"] == "Attended"

    # Privacy: another teammate cannot read a PRIVATE contact's history.
    private = Contact(name="Private P", owner_id=user.id, is_private=True)
    db.add(private)
    db.commit()
    other = user_factory(email="evt-other@fundslccllc.com")
    other_headers = {"Authorization": f"Bearer {create_access_token(user_id=other.id)}"}
    assert (
        client.get(
            f"/api/contacts/{private.id}/events", headers=other_headers
        ).status_code
        == 404
    )
