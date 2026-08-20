"""The voice door to Satchel's public-web pass — gates and shape."""

from typing import Callable
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models import Contact, User
from app.services.tool_dispatch import dispatch_tool_call
from app.services.web_enrich import WebProposal


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


def test_requires_charter_then_returns_proposals(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    contact = Contact(name="Gap Person", owner_id=user.id, is_private=False)
    db.add(contact)
    db.commit()

    r = dispatch_tool_call("satchel_web_check", {"contact_id": contact.id}, user, db)
    assert r["error"] == "charter_required"

    _ack(db, user)
    proposal = WebProposal(
        contact_id=contact.id,
        contact_name="Gap Person",
        fields={"title": "CFO", "email": "gap@shieldworks.fake"},
        sources=["https://shield.example/team"],
    )

    async def fake_run(contacts, gaps, **kw):
        return [proposal], 1, 2

    with patch("app.services.web_enrich.propose_from_web", side_effect=fake_run):
        r = dispatch_tool_call(
            "satchel_web_check", {"contact_id": contact.id}, user, db
        )
    assert r["checked"] == 1
    assert r["proposals"][0]["fields"]["email"] == "gap@shieldworks.fake"
    assert r["proposals"][0]["sources"] == ["https://shield.example/team"]


def test_only_owned_contacts_and_no_gaps_short_circuits(
    db: Session, user_factory: Callable[..., User]
) -> None:
    owner = user_factory()
    other = user_factory(email="satchel-other@otherteam.fake")
    _ack(db, other)
    contact = Contact(name="Not Yours", owner_id=owner.id, is_private=False)
    db.add(contact)
    db.commit()

    r = dispatch_tool_call("satchel_web_check", {"contact_id": contact.id}, other, db)
    assert r["error"] == "not_owned"

    # Fully-filled contact → nothing to hunt, no search spent.
    _ack(db, owner)
    full = Contact(
        name="Complete C",
        owner_id=owner.id,
        title="CEO",
        company_name="Full Co",
        email="c@full.fake",
        cell_phone="+1 555 000 1111",
        office_phone="+1 555 000 2222",
        is_private=False,
    )
    db.add(full)
    db.commit()
    r = dispatch_tool_call("satchel_web_check", {"contact_id": full.id}, owner, db)
    assert r.get("checked") == 0
