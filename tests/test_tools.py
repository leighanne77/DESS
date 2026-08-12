"""Tests for the tool schemas and registry.

The validation tests here are the *real* defense against bad LLM tool
calls — Slice 5's dispatcher relies on Pydantic raising on any
off-spec input. So we test the schemas hard.
"""

import pytest
from pydantic import ValidationError

from app.services.tools import (
    TOOL_REGISTRY,
    CreateContactInput,
    PipelineSummaryInput,
    SearchContactsInput,
    UpdateContactInput,
    anthropic_tool_definitions,
)


def test_search_accepts_all_fields_optional() -> None:
    SearchContactsInput()
    SearchContactsInput(query="mare island")
    SearchContactsInput(primary_fund="Maritime")
    SearchContactsInput(contact_type="Portfolio")


def test_search_rejects_unknown_fund() -> None:
    with pytest.raises(ValidationError):
        SearchContactsInput(primary_fund="Aerospace")


def test_search_rejects_unknown_contact_type() -> None:
    with pytest.raises(ValidationError):
        SearchContactsInput(contact_type="Drinking-Buddy")


def test_create_requires_name() -> None:
    with pytest.raises(ValidationError):
        CreateContactInput()


def test_create_accepts_minimal_fields() -> None:
    contact = CreateContactInput(
        name="Jane Doe", fly_status="Maybe Must Fly", is_private=True
    )
    assert contact.name == "Jane Doe"
    assert contact.primary_fund == "General"
    assert contact.contact_type == "Other"
    assert contact.is_private is True
    assert contact.fly_status == "Maybe Must Fly"


def test_create_requires_fly_status() -> None:
    """fly_status is required — Claude must ask the user for it."""
    with pytest.raises(ValidationError):
        CreateContactInput(name="Jane Doe")


def test_create_requires_is_private() -> None:
    """The 'share with the team' answer is required on EVERY create —
    like fly_status, Claude must ask; silence is not consent either way."""
    with pytest.raises(ValidationError):
        CreateContactInput(name="Jane Doe", fly_status="Maybe Must Fly")


def test_create_validates_email_format() -> None:
    with pytest.raises(ValidationError):
        CreateContactInput(name="X", email="not-an-email", fly_status="Must Fly")


def test_update_requires_contact_id_positive() -> None:
    with pytest.raises(ValidationError):
        UpdateContactInput(contact_id=0)
    with pytest.raises(ValidationError):
        UpdateContactInput(contact_id=-1)
    UpdateContactInput(contact_id=42)


def test_update_allows_partial_update() -> None:
    payload = UpdateContactInput(contact_id=1, name="Renamed")
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"contact_id": 1, "name": "Renamed"}


def test_pipeline_summary_accepts_no_args() -> None:
    PipelineSummaryInput()
    PipelineSummaryInput(primary_fund="Energy")


def test_registry_has_all_expected_tools() -> None:
    assert set(TOOL_REGISTRY.keys()) == {
        "search_contacts",
        "create_contact",
        "update_contact",
        "delete_contact",
        "link_contacts",
        "find_intro_paths",
        "get_pipeline_summary",
        "request_change",
        "resolve_change_request",
        "create_google_task",
        "transfer_contact",
        "create_next_step",
        "complete_next_step",
        "create_event",
        "list_events",
        "update_event",
        "record_event_invite",
        "accept_satchel_charter",
        "satchel_web_check",
        "satchel_org_scout",
    }


def test_anthropic_definitions_have_required_keys() -> None:
    for tool in anthropic_tool_definitions():
        assert "name" in tool
        assert "description" in tool and len(tool["description"]) > 20
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
