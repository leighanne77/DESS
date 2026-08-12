"""Retired contacts — kept in the CRM, mostly hidden (2026-08-11).

The posture under test: a retired contact drops out of searches, pipeline
summaries, and intro paths UNLESS retired people are explicitly asked
for. Direct fetch by id still works — naming the person is the ask.
"""

from typing import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Contact, User
from app.security import create_access_token
from app.services.intro_paths import ContactNode, gate_reason
from app.services.tool_dispatch import dispatch_tool_call


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id=user.id)}"}


@pytest.fixture
def owner_with_pair(
    db: Session, user_factory: Callable[..., User]
) -> tuple[User, Contact, Contact]:
    """One user owning one active and one retired contact."""
    user = user_factory()
    active = Contact(name="Active Person", primary_fund="Maritime", owner_id=user.id)
    retired = Contact(
        name="Retired Admiral",
        primary_fund="Maritime",
        owner_id=user.id,
        retired=True,
    )
    db.add_all([active, retired])
    db.commit()
    return user, active, retired


def test_search_hides_retired_by_default(
    db: Session, owner_with_pair: tuple[User, Contact, Contact]
) -> None:
    user, active, retired = owner_with_pair
    result = dispatch_tool_call("search_contacts", {}, user, db)
    names = [c["name"] for c in result["results"]]
    assert "Active Person" in names
    assert "Retired Admiral" not in names


def test_search_only_retired_on_explicit_ask(
    db: Session, owner_with_pair: tuple[User, Contact, Contact]
) -> None:
    user, *_ = owner_with_pair
    result = dispatch_tool_call("search_contacts", {"retired_filter": "only"}, user, db)
    names = [c["name"] for c in result["results"]]
    assert names == ["Retired Admiral"]
    # And the payload carries the label the UI badges from.
    assert result["results"][0]["retired"] is True


def test_search_include_returns_everyone(
    db: Session, owner_with_pair: tuple[User, Contact, Contact]
) -> None:
    user, *_ = owner_with_pair
    result = dispatch_tool_call(
        "search_contacts", {"retired_filter": "include"}, user, db
    )
    names = {c["name"] for c in result["results"]}
    assert {"Active Person", "Retired Admiral"} <= names


def test_pipeline_summary_excludes_retired(
    db: Session, owner_with_pair: tuple[User, Contact, Contact]
) -> None:
    user, *_ = owner_with_pair
    result = dispatch_tool_call("get_pipeline_summary", {}, user, db)
    assert result["total"] == 1  # the retired one is not in the picture


def test_update_contact_sets_and_clears_retired(
    db: Session, owner_with_pair: tuple[User, Contact, Contact]
) -> None:
    user, active, _ = owner_with_pair
    result = dispatch_tool_call(
        "update_contact", {"contact_id": active.id, "retired": True}, user, db
    )
    assert "error" not in result
    db.refresh(active)
    assert active.retired is True

    result = dispatch_tool_call(
        "update_contact", {"contact_id": active.id, "retired": False}, user, db
    )
    assert "error" not in result
    db.refresh(active)
    assert active.retired is False


def test_intro_gate_refuses_retired_intermediaries() -> None:
    """Retired people are never offered as go-betweens; the pure engine
    gates them exactly like the blocklist and the opt-in rules."""
    assert gate_reason("Must Fly", "APPROVED", retired=True) == "retired"
    assert gate_reason("Must Fly", "APPROVED", retired=False) is None
    node = ContactNode(
        contact_id=1,
        name="Retired Admiral",
        fly_status="Must Fly",
        opt_in_status="APPROVED",
        retired=True,
    )
    assert gate_reason(node.fly_status, node.opt_in_status, node.retired) == "retired"


def test_rest_list_hides_retired_unless_asked(
    client: TestClient, db: Session, owner_with_pair: tuple[User, Contact, Contact]
) -> None:
    user, active, retired = owner_with_pair
    resp = client.get("/api/contacts", headers=_auth_headers(user))
    names = [c["name"] for c in resp.json()]
    assert "Retired Admiral" not in names

    resp = client.get(
        "/api/contacts", params={"include_retired": "true"}, headers=_auth_headers(user)
    )
    names = [c["name"] for c in resp.json()]
    assert "Retired Admiral" in names

    # Direct GET by id is the explicit ask — a retired contact still loads.
    resp = client.get(f"/api/contacts/{retired.id}", headers=_auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["retired"] is True
