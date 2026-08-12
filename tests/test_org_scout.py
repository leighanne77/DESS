"""Satchel org scout — discovery gates, parsing, and the no-write rule."""

import asyncio
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models import Contact, User
from app.services.org_scout import ScoutCandidate, scout_org
from app.services.tool_dispatch import dispatch_tool_call


def _ack(db: Session, user: User) -> None:
    from app.services.audit import write_audit_row

    write_audit_row(
        db,
        user,
        action="satchel_charter_acknowledged",
        target_type="user",
        target_id=user.id,
        payload_hash=None,
        payload_metadata={},
    )


def test_requires_charter_then_flags_existing_contacts(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    params = {
        "organization": "Shield Dynamics",
        "looking_for": "invite to the maritime briefing DIN-2026-001",
    }

    r = dispatch_tool_call("satchel_org_scout", params, user, db)
    assert r["error"] == "charter_required"

    _ack(db, user)
    # One candidate already in the book, one genuinely new.
    known = Contact(name="Dana Vold", owner_id=user.id, is_private=False)
    db.add(known)
    db.commit()

    async def fake_scout(organization, looking_for, **kw):
        return (
            [
                ScoutCandidate(
                    name="Dana Vold",
                    title="VP Maritime",
                    sources=["https://shield.example/team"],
                ),
                ScoutCandidate(
                    name="New Person",
                    title="Director, Autonomy",
                    why="runs the autonomy line",
                    sources=["https://shield.example/press"],
                ),
            ],
            4,
            None,
        )

    with patch("app.services.org_scout.scout_org", side_effect=fake_scout):
        r = dispatch_tool_call("satchel_org_scout", params, user, db)

    assert r["searches"] == 4
    by_name = {c["name"]: c for c in r["candidates"]}
    assert by_name["Dana Vold"]["already_in_crm"] == known.id
    assert by_name["New Person"]["already_in_crm"] is None
    # Nothing was created — the scout proposes, the intake writes.
    assert db.query(Contact).count() == 1
    assert "create_contact" in r["reminder"]


def test_privacy_other_users_private_contact_not_flagged(
    db: Session, user_factory: Callable[..., User]
) -> None:
    """The already-in-CRM check runs through the caller's VISIBLE
    contacts — a teammate's private contact stays invisible."""
    owner = user_factory()
    caller = user_factory(email="scout-other@fundslccllc.com")
    _ack(db, caller)
    db.add(Contact(name="Hidden Match", owner_id=owner.id, is_private=True))
    db.commit()

    async def fake_scout(organization, looking_for, **kw):
        return (
            [ScoutCandidate(name="Hidden Match", sources=["https://x.example"])],
            1,
            None,
        )

    with patch("app.services.org_scout.scout_org", side_effect=fake_scout):
        r = dispatch_tool_call(
            "satchel_org_scout",
            {"organization": "X Corp", "looking_for": "briefing invites"},
            caller,
            db,
        )
    assert r["candidates"][0]["already_in_crm"] is None


def test_scout_org_parses_and_filters() -> None:
    """Service-level: JSON parsing, nameless candidates dropped, non-http
    sources filtered, search count read from server_tool_use blocks."""
    reply = SimpleNamespace(
        content=[
            SimpleNamespace(type="server_tool_use", name="web_search"),
            SimpleNamespace(type="server_tool_use", name="web_search"),
            SimpleNamespace(
                type="text",
                text=(
                    '{"candidates": ['
                    '{"name": "Ada Chen", "title": "CTO", '
                    '"company_name": "Shield Labs", "email": null, '
                    '"office_phone": null, "why": "owns the tech agenda", '
                    '"sources": ["https://shield.example/leadership", '
                    '"not-a-url"]},'
                    '{"name": "  ", "title": "ghost"},'
                    '{"name": "No Source Sam", "sources": []}'
                    '], "note": "team page dated 2026"}'
                ),
            ),
        ]
    )

    async def fake_call(**kw):
        return reply

    with patch("app.services.org_scout.call_claude", side_effect=fake_call):
        candidates, searches, note = asyncio.run(
            scout_org("Shield Labs", "briefing invites")
        )

    assert searches == 2
    assert note == "team page dated 2026"
    assert [c.name for c in candidates] == ["Ada Chen", "No Source Sam"]
    assert candidates[0].sources == ["https://shield.example/leadership"]
    assert candidates[0].why == "owns the tech agenda"
