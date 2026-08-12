"""Pydantic schemas for Contact API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Outreach consent for the Phase 5 warm-introduction engine. Only
# APPROVED contacts may be offered as a node on an intro path; PENDING
# (default) and DENIED are never offered.
OptInStatus = Literal["APPROVED", "PENDING", "DENIED"]


class ContactBase(BaseModel):
    """Shared fields for create/update/read."""

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    cell_phone: str | None = Field(None, max_length=20)
    office_phone: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=255)
    company_name: str | None = Field(None, max_length=255)
    notes: str | None = None
    primary_fund: str = Field(default="General", max_length=50)
    contact_type: str = Field(default="Other", max_length=50)
    sectors: list[str] = Field(default_factory=list)
    is_private: bool = False
    opt_in_status: OptInStatus = "PENDING"
    # Retired — kept in the CRM, mostly hidden from lists/search/intros
    # unless explicitly requested.
    retired: bool = False
    metro: str | None = Field(None, max_length=100)


class ContactCreate(ContactBase):
    """Request body for POST /contacts."""


class ContactUpdate(BaseModel):
    """Request body for PATCH /contacts/{id} — all fields optional."""

    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    cell_phone: str | None = Field(None, max_length=20)
    office_phone: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=255)
    company_name: str | None = Field(None, max_length=255)
    notes: str | None = None
    primary_fund: str | None = None
    contact_type: str | None = None
    sectors: list[str] | None = None
    is_private: bool | None = None
    opt_in_status: OptInStatus | None = None
    metro: str | None = Field(None, max_length=100)


class ContactRead(ContactBase):
    """Response body for GET /contacts."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    shared_with: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ContactShare(BaseModel):
    """Request body for POST /contacts/{id}/share."""

    user_id: int = Field(..., gt=0)
