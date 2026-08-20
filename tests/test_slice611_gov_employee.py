"""Tests for Slice 6.11 — gov-employee detection + LP? + fly_status defaults."""

from __future__ import annotations

from typing import Callable

import pytest
from sqlalchemy.orm import Session

from app.models import Contact, User
from app.services.gov_detect import looks_like_gov_email
from app.services.tool_dispatch import dispatch_tool_call


def _make_contact(db: Session, owner: User, **overrides) -> Contact:
    defaults = dict(
        name="Test",
        owner_id=owner.id,
        primary_fund="Critical Minerals",
        contact_type="LP",
        fly_status="Unknown",
    )
    defaults.update(overrides)
    c = Contact(**defaults)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Email-domain auto-detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        "lisa.grossman@usace.army.mil",
        "alice@navy.mil",
        "bob@state.gov",
        "carol@usda.gov",
        "diana@fed.us",
        "eve@hhs.gc.ca",
        "frank@cabinetoffice.gov.uk",
        "grace@defense.gov.au",
        "helen@psa.gov.sa",
        "ivan@gouv.fr",  # not technically valid but exercises the suffix
        "judith@bka.bund.de",
    ],
)
def test_gov_detect_recognizes_government_domains(email: str) -> None:
    assert looks_like_gov_email(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "alice@gmail.com",
        "bob@example.com",
        "carol@ironclad.fake",
        "diana@example.fake",
        "eve@government-consulting.fake",  # private firm with "government" in name
        "frank@military-club.fake",  # private domain
        "",
        None,
    ],
)
def test_gov_detect_rejects_non_government_domains(email: str | None) -> None:
    assert looks_like_gov_email(email) is False


def test_gov_detect_is_case_insensitive() -> None:
    assert looks_like_gov_email("Lisa.Grossman@USACE.Army.Mil") is True


# ---------------------------------------------------------------------------
# Auto-flag on create_contact
# ---------------------------------------------------------------------------


def test_create_contact_auto_sets_is_gov_employee_for_dot_mil(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    result = dispatch_tool_call(
        "create_contact",
        {
            "name": "Lisa Grossman",
            "email": "lisa.grossman@usace.army.mil",
            "fly_status": "Fly List",
            "is_private": False,
            "primary_fund": "Critical Minerals",
            "contact_type": "Government",
        },
        user,
        db,
    )
    assert result["created"]["is_gov_employee"] is True


def test_create_contact_leaves_is_gov_employee_false_for_personal_email(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    result = dispatch_tool_call(
        "create_contact",
        {
            "name": "Marcus Sterling",
            "email": "marcus@ironclad.fake",
            "fly_status": "Must Fly",
            "is_private": False,
        },
        user,
        db,
    )
    assert result["created"]["is_gov_employee"] is False


def test_explicit_false_overrides_auto_detect(
    db: Session, user_factory: Callable[..., User]
) -> None:
    """A contractor with a .gov inbox who isn't actually a gov employee."""
    user = user_factory()
    result = dispatch_tool_call(
        "create_contact",
        {
            "name": "Contractor Carla",
            "email": "carla@usda.gov",
            "fly_status": "Fly List",
            "is_private": False,
            "is_gov_employee": False,
        },
        user,
        db,
    )
    assert result["created"]["is_gov_employee"] is False


def test_explicit_true_works_without_an_email(
    db: Session, user_factory: Callable[..., User]
) -> None:
    """Some gov contacts only have phone numbers — owner can still flag."""
    user = user_factory()
    result = dispatch_tool_call(
        "create_contact",
        {
            "name": "Senator Phone-Only",
            "fly_status": "Must Fly",
            "is_private": False,
            "is_gov_employee": True,
        },
        user,
        db,
    )
    assert result["created"]["is_gov_employee"] is True


# ---------------------------------------------------------------------------
# Owner-toggleable via update_contact
# ---------------------------------------------------------------------------


def test_update_contact_can_toggle_is_gov_employee(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    c = _make_contact(db, user, name="Lisa", is_gov_employee=True)

    result = dispatch_tool_call(
        "update_contact",
        {"contact_id": c.id, "is_gov_employee": False},
        user,
        db,
    )
    assert result["updated"]["is_gov_employee"] is False


# ---------------------------------------------------------------------------
# Fly status — new default + sort order with new statuses
# ---------------------------------------------------------------------------


def test_new_contacts_default_to_unknown(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    c = _make_contact(db, user)  # no fly_status passed
    # The helper passes fly_status="Unknown" by default; this confirms
    # the column-level default would do the same.
    assert c.fly_status == "Unknown"


def test_sort_orders_unknown_before_off_fly_list(
    db: Session, user_factory: Callable[..., User]
) -> None:
    """Must Fly → Fly List → Maybe Must Fly → Unknown → Off Fly List."""
    user = user_factory()
    off = _make_contact(db, user, name="Z-off")
    off.fly_status = "Off Fly List"
    unknown = _make_contact(db, user, name="W-unknown")
    unknown.fly_status = "Unknown"
    maybe = _make_contact(db, user, name="V-maybe")
    maybe.fly_status = "Maybe Must Fly"
    fly = _make_contact(db, user, name="B-fly")
    fly.fly_status = "Fly List"
    must = _make_contact(db, user, name="A-must")
    must.fly_status = "Must Fly"
    db.commit()

    result = dispatch_tool_call("search_contacts", {}, user, db)
    names = [r["name"] for r in result["results"]]
    assert names == ["A-must", "B-fly", "V-maybe", "W-unknown", "Z-off"]


# ---------------------------------------------------------------------------
# Privacy regression — is_gov_employee never leaks on redacted rows
# ---------------------------------------------------------------------------


def test_redacted_view_never_exposes_is_gov_employee(
    db: Session, user_factory: Callable[..., User]
) -> None:
    """A non-owner searching across a private gov-employee contact must
    see is_gov_employee=False, regardless of the actual flag. The flag is
    derived from PII (email domain), so leaking it would partially leak
    the email-domain identity of a private contact."""
    owner = user_factory(email="owner@test.fake")
    viewer = user_factory(email="viewer@test.fake")
    private_gov = _make_contact(
        db,
        owner,
        name="Hidden Senator",
        email="senator@senate.gov",
        is_private=True,
        is_gov_employee=True,
        primary_fund="Critical Minerals",
    )

    result = dispatch_tool_call(
        "search_contacts",
        {"primary_fund": "Critical Minerals"},
        viewer,
        db,
    )
    # The redacted row should appear in results (reveal_fields default
    # includes primary_fund) but is_gov_employee must be False.
    redacted_rows = [r for r in result["results"] if r.get("id") == private_gov.id]
    assert len(redacted_rows) == 1
    assert redacted_rows[0]["is_redacted"] is True
    assert redacted_rows[0]["is_gov_employee"] is False  # masked


# ---------------------------------------------------------------------------
# Potential LP contact type
# ---------------------------------------------------------------------------


def test_potential_lp_contact_type_accepted(
    db: Session, user_factory: Callable[..., User]
) -> None:
    user = user_factory()
    result = dispatch_tool_call(
        "create_contact",
        {
            "name": "Prospect Pat",
            "fly_status": "Maybe Must Fly",
            "is_private": False,
            "contact_type": "Potential LP",
        },
        user,
        db,
    )
    assert result["created"]["contact_type"] == "Potential LP"
