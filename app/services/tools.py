"""Tool schemas for Claude.

Each tool input is a Pydantic model with explicit fields and (where
possible) Literal types — no free-form dicts. This is the surface
Claude is allowed to call. The dispatcher in app/services/tool_dispatch
(Slice 5) validates every Claude-generated tool call against these
schemas before executing anything.

Adding a new tool:
1. Define a `*Input(BaseModel)` with strict types.
2. Add a `ToolSpec` entry in `TOOL_REGISTRY`.
3. Wire the handler in app/services/tool_dispatch.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.services.patina import PATINA_OVERRIDES_MAX, ChangeRequestPayload, PatinaItem

PrimaryFund = Literal["Critical Minerals", "Maritime", "Energy", "General"]
ContactType = Literal[
    "LP",
    "Potential LP",
    "Portfolio",
    "Government",
    "Intermediary",
    "Advisor",
    "Inspiration",
    "Other",
]
Gender = Literal["Female", "Male", "Unknown"]
# Phase 2 Slice 6.5 — fields the OWNER may put in reveal_fields. PII
# (name, email, phones, title, notes, image_url) is intentionally
# excluded; those columns are never legal to expose on a redacted row.
RevealField = Literal[
    "primary_fund",
    "company_name",
    "sectors",
    "contact_type",
    "country",
    "lp_subtype",
    "fly_status",
    "ex_government",
    "gender",
]
LpSubtype = Literal[
    "Sovereign Wealth Fund",
    "Family Office",
    "Pension",
    "Endowment",
    "Insurance",
    "Foundation",
    "Other",
]
# Required field on every contact.
#   "Must Fly"       = work with them if at all possible (solid plane)
#   "Fly List"       = safe to work with if required (outline plane)
#   "Maybe Must Fly" = under review (dotted plane) — renamed from
#                      "Not Sure Yet" so the label matches the intent
#   "Unknown"        = haven't decided yet (no plane shown) — default
#                      for new entries
#   "Off Fly List"   = explicitly removed; only the contact's owner can
#                      set this. Non-owners must request review
#                      (Phase 2). Off-list contacts still appear in
#                      search results, just last, so they aren't lost.
#                      No plane + ripped channels.
# Values + their warmth + sort order are owned by app/services/fly_status
# (test_fly_status.py guards that this Literal still matches that set).
FlyStatus = Literal["Must Fly", "Fly List", "Maybe Must Fly", "Unknown", "Off Fly List"]
# Ex-government background. Filter for "show me ex-government contacts."
# Default "Don't Know" so the field is genuinely optional on input.
ExGovernment = Literal["Yes", "No", "Don't Know"]
# Phase 5 warm-introduction engine — outreach consent gate. Only
# APPROVED contacts may be offered as a node on an intro path; PENDING
# (default) and DENIED are never offered. Owner-only to change.
OptInStatus = Literal["APPROVED", "PENDING", "DENIED"]
# Phase 5 — relationship (edge) descriptors. relationship_type is
# metadata; shared_history is the v1 connection signal the engine scores.
RelationshipType = Literal[
    "colleague",
    "co-investor",
    "board",
    "introduced_by",
    "personal",
    "advisor",
    "service_provider",
    "other",
]
SharedHistory = Literal["none", "some", "strong"]


class SearchContactsInput(BaseModel):
    """Filter contacts by free-text query and/or fund/type."""

    query: str | None = Field(
        None,
        description=(
            "Free-text search across name, company_name, title, and notes. "
            "Case-insensitive."
        ),
        max_length=200,
    )
    primary_fund: PrimaryFund | None = Field(None, description="Restrict to one fund.")
    contact_type: ContactType | None = Field(
        None, description="Restrict to one contact type."
    )
    gender: Gender | None = Field(
        None,
        description=(
            "Restrict to one gender. Use when the user asks for women or "
            "men specifically (e.g. 'show me women in Maritime')."
        ),
    )
    country: str | None = Field(
        None,
        description=(
            "Restrict to one country. Use canonical full names like "
            "'United States', 'Saudi Arabia', 'Canada'. Map natural-"
            "language forms ('U.S.', 'Saudi', 'KSA', 'Canadian') to the "
            "canonical name."
        ),
        max_length=100,
    )
    metro: str | None = Field(
        None,
        description=(
            "Restrict to one metro / city (e.g. 'Mobile', 'Houston'). "
            "Use for 'who do we know in Mobile' queries."
        ),
        max_length=100,
    )
    lp_subtype: LpSubtype | None = Field(
        None,
        description=(
            "Restrict to one LP subtype (Sovereign Wealth Fund, Family "
            "Office, Pension, Endowment, Insurance, Foundation, Other). "
            "Useful for queries like 'show me sovereign wealth fund "
            "contacts'."
        ),
    )
    fly_status: FlyStatus | None = Field(
        None,
        description=(
            "Restrict to one fly_status. 'Must Fly' = priority targets. "
            "'Fly List' = acceptable. 'Maybe Must Fly' = under review. "
            "'Unknown' = haven't decided. Map natural-language forms "
            "('must-fly', 'priority list', 'top contacts') to 'Must Fly'."
        ),
    )
    ex_government: ExGovernment | None = Field(
        None,
        description=(
            "Restrict by ex-government background. 'Yes' = formerly held "
            "a government role. Use for queries like 'show me ex-gov "
            "contacts in critical minerals'."
        ),
    )
    opt_in_status: OptInStatus | None = Field(
        None,
        description=(
            "Restrict by intro-outreach consent. 'PENDING' = not yet "
            "approved for introductions (the default for every contact); "
            "'APPROVED' = cleared to be offered as an intro path; "
            "'DENIED' = explicitly excluded. Use for 'who still needs "
            "intro approval' (PENDING) data-cleanup passes."
        ),
    )
    event: str | None = Field(
        None,
        max_length=255,
        description=(
            "Restrict to contacts tied to one EVENT — catalog number "
            "(e.g. 'DIN-2026-001') or a unique title fragment. Use for "
            "'who did we invite to the dinner' / 'who attended X'."
        ),
    )
    event_status: Literal["Invited", "Attended"] | None = Field(
        None,
        description=(
            "With `event`: 'Attended' = people who came; 'Invited' = "
            "people invited who did NOT attend; omitted = everyone tied "
            "to the event. Map 'invited but didn't come' to 'Invited'."
        ),
    )
    retired_filter: Literal["exclude", "include", "only"] = Field(
        "exclude",
        description=(
            "Retired handling. Default 'exclude' hides retired people; "
            "'only' when the user asks for retired people ('show me "
            "retired contacts'); pass 'include' when they ask to search "
            "everyone including the retired. Never volunteer retired "
            "contacts."
        ),
    )


class AcceptSatchelCharterInput(BaseModel):
    """Record the teammate's acceptance of the Satchel charter — the
    one-time consent that unlocks Satchel's web errands. Call ONLY right
    after the teammate explicitly agrees to the charter in their own
    words; never infer consent."""

    confirmed: bool = Field(
        ...,
        description=(
            "Must be true. Set true ONLY after the teammate has just, "
            "explicitly, accepted the charter."
        ),
    )


class SatchelWebCheckInput(BaseModel):
    """Send Satchel to the PUBLIC WEB for one contact's missing details
    (title, employer, published email). Use for 'tell Satchel to check
    the web for X', 'have Satchel look X up online', 'find X's email
    online'. Returns PROPOSALS with source URLs — nothing is written.
    Read them back; on the user's explicit yes, apply the approved
    values via update_contact (only to fields that are still empty)."""

    contact_id: int = Field(..., gt=0)


class SatchelOrgScoutInput(BaseModel):
    """Send Satchel to find the RIGHT PEOPLE at an organization for a
    stated purpose — people not (necessarily) in the CRM yet. Use for
    'find the right people at X to invite to Y', 'who at X should we
    talk to about Y'. Returns CANDIDATES with source URLs — nothing is
    created. Each person the user wants enters via the normal
    create_contact intake, one at a time."""

    organization: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="The organization to scout, as the user names it.",
    )
    looking_for: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description=(
            "What the people are FOR — the purpose in the user's words, "
            "e.g. 'invite to the maritime briefing DIN-2026-001'."
        ),
    )


class CreateEventInput(BaseModel):
    """Catalogue a DIN event. Use for 'create an event', 'catalog the
    Mobile dinner', 'add the demo day to the events list'. Returns the
    assigned CATALOG NUMBER (e.g. DIN-2026-001) — read it back to the
    user; it is how the team refers to the event from then on."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Short label, e.g. 'Mobile Harbor Dinner'.",
    )
    event_date: str | None = Field(
        None,
        description="Event date as YYYY-MM-DD if the user gave one.",
    )
    location: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)


class ListEventsInput(BaseModel):
    """List catalogued events, optionally filtered by a title substring
    or year. Use for 'what events do we have', 'show me this year's
    events', 'find the Mobile dinner'."""

    query: str | None = Field(
        None, max_length=255, description="Case-insensitive title substring."
    )
    year: int | None = Field(None, ge=2020, le=2100)


class UpdateEventInput(BaseModel):
    """Update a catalogued event's fields. NOTES REPLACE the existing
    notes — to append, first read the current notes from list_events and
    send the merged text."""

    event: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Catalog number (preferred) or unique " "title fragment.",
    )
    title: str | None = Field(None, min_length=1, max_length=255)
    event_date: str | None = Field(None, description="YYYY-MM-DD.")
    location: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)


class RecordEventInviteInput(BaseModel):
    """Tie a contact to an event as Invited or Attended. Use for 'we
    invited X to the dinner', 'mark Y attended DIN-2026-001', 'X came to
    the demo day'. Status only moves FORWARD: recording Attended upgrades
    an Invited row; recording Invited on someone already Attended changes
    nothing. Resolve the contact with search_contacts first."""

    event: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Catalog number (preferred) or a unique " "title fragment.",
    )
    contact_id: int = Field(..., gt=0)
    status: Literal["Invited", "Attended"] = "Invited"
    note: str | None = Field(
        None,
        max_length=2000,
        description=(
            "Event note for THIS person on THIS event — 'brought two "
            "colleagues', 'asked for the deck'. Updates in place on "
            "re-record; omit to leave the existing note alone."
        ),
    )


class CreateContactInput(BaseModel):
    """Create a new contact owned by the current user."""

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = None
    cell_phone: str | None = Field(None, max_length=20)
    office_phone: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=255)
    company_name: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)
    primary_fund: PrimaryFund = "General"
    contact_type: ContactType = "Other"
    sectors: list[str] = Field(default_factory=list, max_length=20)
    # Required — like fly_status, the user must explicitly answer the
    # "share with the team?" question on EVERY create. No default: if
    # Claude calls without it, validation fails and Claude has to ask.
    is_private: bool = Field(
        ...,
        description=(
            "Required. The 'share with the team' choice — ask on every "
            "create: 'Share with the team, or keep private to you?' "
            "share with the team → is_private=false; keep private (the "
            "norm) → is_private=true. Never guess and never assume from "
            "silence — if the user hasn't answered, ask before creating."
        ),
    )
    gender: Gender = "Unknown"
    country: str | None = Field(None, max_length=100)
    metro: str | None = Field(
        None,
        max_length=100,
        description=(
            "Metro / city the contact is in (e.g. 'Mobile', 'Washington "
            "DC', 'Houston'). Free text; map natural forms to a city/metro "
            "name. Powers the warm-intro geography signal (same metro = "
            "warmer connection)."
        ),
    )
    lp_subtype: LpSubtype | None = None
    # Required — the user must explicitly pick. No default. If Claude
    # tries to create a contact without it, validation fails and Claude
    # has to ask the user.
    fly_status: FlyStatus = Field(
        ...,
        description=(
            "Required. 'Must Fly' (work with them if at all possible), "
            "'Fly List' (safe to work with if required), 'Maybe Must "
            "Fly' (under review, dotted plane), or 'Unknown' (haven't "
            "decided, no plane shown). Always ask the user which one — "
            "do not guess. Default to 'Unknown' only if the user "
            "explicitly says 'we don't know'."
        ),
    )
    image_url: str | None = Field(
        None,
        description="Optional headshot URL. Omit if no image is available.",
        max_length=500,
    )
    ex_government: ExGovernment = "Don't Know"
    opt_in_status: OptInStatus = Field(
        "PENDING",
        description=(
            "Intro-outreach consent. Defaults to 'PENDING' — a new "
            "contact is NOT offered as an introduction path until the "
            "owner approves them. Only set 'APPROVED' if the user "
            "explicitly clears this person for introductions; 'DENIED' "
            "to explicitly exclude. Do not guess — leave the default."
        ),
    )
    is_gov_employee: bool | None = Field(
        None,
        description=(
            "Set True for CURRENT government employees of any nation. "
            "If omitted, the server auto-detects from the email domain "
            "(.gov / .mil / .gc.ca / .gov.uk and similar) and sets it "
            "for you. Pass False explicitly to override the auto-detect "
            "(e.g. a contractor with a .gov inbox who isn't actually "
            "a gov employee). Distinct from ex_government — that "
            "tracks former service; this gates the 3-side fund-colored "
            "border on the card."
        ),
    )
    patina_overrides: list[PatinaItem] | None = Field(
        None,
        max_length=PATINA_OVERRIDES_MAX,
        description=(
            "User-set rolodex patina marks. Leave None to use the "
            "automatic per-id pick. Pass [] to explicitly show no "
            "patina. Pass a list of items to override the auto-pick. "
            "See app.services.patina for the discriminated union."
        ),
    )


class UpdateContactInput(BaseModel):
    """Update specific fields on an existing contact. Owner-only."""

    contact_id: int = Field(..., gt=0)
    name: str | None = Field(None, min_length=1, max_length=255)
    email: EmailStr | None = None
    cell_phone: str | None = Field(None, max_length=20)
    office_phone: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=255)
    company_name: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)
    primary_fund: PrimaryFund | None = None
    contact_type: ContactType | None = None
    sectors: list[str] | None = Field(None, max_length=20)
    is_private: bool | None = None
    gender: Gender | None = None
    country: str | None = Field(None, max_length=100)
    metro: str | None = Field(
        None,
        max_length=100,
        description=(
            "Metro / city the contact is in (e.g. 'Mobile', 'Washington "
            "DC', 'Houston'). Free text; map natural forms to a city/metro "
            "name. Powers the warm-intro geography signal (same metro = "
            "warmer connection)."
        ),
    )
    lp_subtype: LpSubtype | None = None
    fly_status: FlyStatus | None = None
    image_url: str | None = Field(None, max_length=500)
    retired: bool | None = Field(
        None,
        description=(
            "Mark this person retired (true) or un-retire them (false). "
            "Retired contacts stay in the CRM but drop out of searches, "
            "summaries, and intro paths unless explicitly asked for."
        ),
    )
    ex_government: ExGovernment | None = None
    opt_in_status: OptInStatus | None = Field(
        None,
        description=(
            "Set the intro-outreach consent. 'APPROVED' clears the "
            "contact to be offered as an introduction path; 'PENDING' "
            "holds them back (default); 'DENIED' excludes them. "
            "Owner-only, audited like any other contact edit."
        ),
    )
    is_gov_employee: bool | None = Field(
        None,
        description=(
            "Toggle the current-government-employee flag. Drives the "
            "3-side fund-colored border on the card. Owner-only."
        ),
    )
    patina_overrides: list[PatinaItem] | None = Field(
        None,
        max_length=PATINA_OVERRIDES_MAX,
        description=(
            "Replace the contact's patina_overrides. Use [] to clear "
            "(show no patina). Use null to revert to the auto-pick — "
            "but Pydantic 'unset' rules mean omitting the field leaves "
            "it unchanged. To go back to auto-pick, the dispatcher needs "
            "an explicit reset; use the reset_patina convention in your "
            "voice grammar."
        ),
    )
    reveal_fields: list[RevealField] | None = Field(
        None,
        max_length=9,
        description=(
            "Owner-only. Controls which columns of a PRIVATE contact "
            "are visible to teammates on a redacted preview. "
            "Allowed values are DIN's safe-metadata whitelist — name, "
            "email, phones, title, notes, and image_url are never "
            "permitted regardless of what you pass. Default is "
            "['primary_fund', 'company_name', 'sectors']; use that "
            "explicitly to reset to default. Ignored on public contacts "
            "(is_private=False)."
        ),
    )


class DeleteContactInput(BaseModel):
    """Soft-delete a contact the current user owns. Sets deleted_at; the
    row stays in the DB but is hidden from every read path that goes
    through visible_contacts_query. Owner-only."""

    contact_id: int = Field(..., gt=0)
    confirm_token: str | None = Field(
        None,
        description=(
            "Server-issued confirmation token. OMIT on the first call — "
            "the result will be confirm_required plus a token. Ask the "
            "user to confirm; only after an explicit yes, call again "
            "passing that exact token. Never invent or reuse tokens."
        ),
    )


class LinkContactsInput(BaseModel):
    """Record that one contact knows another — an edge in the
    who-knows-whom graph the warm-introduction engine walks. Resolve BOTH
    people with search_contacts first to get their ids. The tie is stored
    from→to but the engine treats it as mutual for reachability."""

    from_contact_id: int = Field(..., gt=0)
    to_contact_id: int = Field(..., gt=0)
    relationship_type: RelationshipType = Field(
        "other",
        description=(
            "How the two are connected: colleague, co-investor, board "
            "(shared board seat), introduced_by, personal, advisor, "
            "service_provider, or other."
        ),
    )
    shared_history: SharedHistory = Field(
        "none",
        description=(
            "Coarse strength of shared professional history between the "
            "two — 'strong' (years overlapping or multiple ties), 'some' "
            "(one clear overlap), or 'none' (default, or when unsure). "
            "This is the connection signal the intro engine scores."
        ),
    )
    notes: str | None = Field(
        None,
        max_length=500,
        description="Optional context, e.g. 'co-board at Acme 2019-22'.",
    )

    @model_validator(mode="after")
    def _distinct_contacts(self) -> "LinkContactsInput":
        if self.from_contact_id == self.to_contact_id:
            raise ValueError("from_contact_id and to_contact_id must differ")
        return self


class FindIntroPathsInput(BaseModel):
    """Find the warmest 1–2 hop introduction paths to a target contact.

    Resolve the target with search_contacts FIRST to get their id. The
    engine walks the who-knows-whom graph (the edges recorded by
    link_contacts), gates out blocklisted / non-opted-in intermediaries,
    and returns paths best-first. Only contacts the caller can see are
    ever used or named."""

    target_contact_id: int = Field(
        ...,
        gt=0,
        description=(
            "The contact we want a warm introduction TO. Resolve the "
            "person's name to their id via search_contacts first."
        ),
    )
    max_results: int = Field(
        5,
        ge=1,
        le=10,
        description="How many ranked paths to return (default 5).",
    )


class PipelineSummaryInput(BaseModel):
    """Get a fund-level summary of visible contacts.

    Optional primary_fund narrows the summary to one fund.
    """

    primary_fund: PrimaryFund | None = None


class RequestChangeInput(BaseModel):
    """File a change request against a contact you don't own. The
    contact's owner reviews and approves or disapproves."""

    contact_id: int = Field(..., gt=0)
    payload: ChangeRequestPayload
    reason: str | None = Field(None, max_length=500)


class ResolveChangeRequestInput(BaseModel):
    """Owner only: approve or disapprove a pending request. Approve
    applies the requested change to the contact; disapprove leaves the
    contact untouched. Either way the request is closed and audited."""

    request_id: int = Field(..., gt=0)
    decision: Literal["approve", "disapprove"]
    note: str | None = Field(None, max_length=500)


class TransferContactInput(BaseModel):
    """Move ownership of a contact from the current owner to a teammate.

    Authorization (enforced in the handler):
      - the calling user must be the current owner, OR
      - the calling user must have role='admin' (admin bypass — needed
        when reassigning a teammate's contacts).
    Immediate effect; no accept-step on the receiving side.
    """

    contact_id: int = Field(..., gt=0)
    new_owner_email: EmailStr = Field(
        ...,
        description=(
            "Email of the DIN teammate who will become the new owner "
            "(e.g. sam@example.com, jordan@example.com). "
            "Must be a member of the DIN team — non-team emails are "
            "rejected."
        ),
    )
    confirm_token: str | None = Field(
        None,
        description=(
            "Server-issued confirmation token (two-step, same as "
            "delete_contact): omit on the first call, receive "
            "confirm_required + a token, ask the user, and re-call with "
            "the token only after an explicit yes. The token is bound to "
            "this exact contact AND recipient — changing either needs a "
            "fresh confirmation."
        ),
    )


class CreateNextStepInput(BaseModel):
    """Add a forward-looking todo to a contact's Next Steps activity log.

    Owner is the teammate who owes the action — independent of the
    contact's owner (common: a contact you own with a step assigned to
    a teammate to call). Resolves to one of the three DIN team emails.
    Title is the action (e.g. 'call about Maritime deck' — the contact
    name is automatically prefixed in Google Tasks).
    """

    contact_id: int = Field(..., gt=0)
    title: str = Field(..., min_length=1, max_length=255)
    owner_email: EmailStr = Field(
        ...,
        description=(
            "Email of the DIN teammate who owes the action. Resolves to "
            "alex@example.com, sam@example.com, or "
            "jordan@example.com."
        ),
    )


class CompleteNextStepInput(BaseModel):
    """Mark a next-step done. Only the step's owner or the contact's
    owner can complete it (enforced in the dispatcher)."""

    next_step_id: int = Field(..., gt=0)


class CreateGoogleTaskInput(BaseModel):
    """File a "Talk to <Owner>" reminder in the calling user's own
    Google Tasks. Owner is derived from contact_id by the dispatcher —
    don't pass owner_name, the model would just drift."""

    contact_id: int = Field(..., gt=0)
    note: str | None = Field(
        None,
        max_length=500,
        description=(
            "Optional context for the task body (e.g. 'follow up on the "
            "Maritime deck'). Leave null for a bare reminder."
        ),
    )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]

    def to_anthropic_dict(self) -> dict[str, Any]:
        """Render as the dict shape Anthropic's tools= parameter expects."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_contacts": ToolSpec(
        name="search_contacts",
        description=(
            "Search the contact database. Returns contacts visible to the "
            "current user, filtered by the optional query, primary_fund, "
            "and contact_type. Always run this before suggesting actions "
            "on a person or company."
        ),
        input_model=SearchContactsInput,
    ),
    "create_contact": ToolSpec(
        name="create_contact",
        description=(
            "Add a new contact to the database, owned by the current user. "
            "Use only when the user has clearly asked to create a new "
            "record. Confirm key fields (name, company) with the user "
            "before calling if any are ambiguous."
        ),
        input_model=CreateContactInput,
    ),
    "update_contact": ToolSpec(
        name="update_contact",
        description=(
            "Update specific fields on a contact the current user owns. "
            "Pass only the fields that should change. Returns 404 if the "
            "contact is not visible; 403 if visible but not owned."
        ),
        input_model=UpdateContactInput,
    ),
    "delete_contact": ToolSpec(
        name="delete_contact",
        description=(
            "Soft-delete a contact the current user owns. The row stays "
            "in the DB with deleted_at set; it disappears from every read "
            "path. DESTRUCTIVE — always confirm with the user before "
            "calling this (e.g. 'Delete \"Jane Doe\" — are you sure?'). "
            "Returns 404 if the contact is not visible; 403 if visible "
            "but not owned."
        ),
        input_model=DeleteContactInput,
    ),
    "link_contacts": ToolSpec(
        name="link_contacts",
        description=(
            "Record that two contacts know each other — an edge in the "
            "relationship graph used to find warm introduction paths. "
            "Resolve BOTH people via search_contacts first to get their "
            "ids, then call with from_contact_id, to_contact_id, the "
            "relationship_type, and shared_history. Re-recording the same "
            "pair + type updates it in place (no duplicates). Use when the "
            "user says things like 'Ada and Ben worked together at Acme' "
            "or 'Carol can introduce us to the admiral'. Both contacts "
            "must be visible to the caller."
        ),
        input_model=LinkContactsInput,
    ),
    "find_intro_paths": ToolSpec(
        name="find_intro_paths",
        description=(
            "Find warm-introduction paths to a target contact — answers "
            "'how do I get a warm intro to X?', 'who can introduce us to "
            "X?', 'find me a way in to X'. Resolve the target via "
            "search_contacts FIRST to get their id, then call with "
            "target_contact_id. Returns ranked paths (warmest first): each "
            "path names whom to reach out to and the chain through to the "
            "target. The engine only uses contacts visible to you, and "
            "drops anyone Off Fly List or not opted in for intros. An "
            "empty paths list means no usable warm path was found — say so "
            "plainly rather than inventing one."
        ),
        input_model=FindIntroPathsInput,
    ),
    "get_pipeline_summary": ToolSpec(
        name="get_pipeline_summary",
        description=(
            "Return a high-level breakdown of visible contacts grouped by "
            "fund and contact_type. Useful for 'what's in my pipeline' "
            "questions. Optional primary_fund narrows to one fund."
        ),
        input_model=PipelineSummaryInput,
    ),
    "request_change": ToolSpec(
        name="request_change",
        description=(
            "File a change request against a contact you don't own. Use "
            "when the user (a non-owner) wants to take a contact off the "
            "fly list (kind=off_fly_list) or override their patina marks "
            "(kind=patina_override). The contact's owner will review and "
            "approve or disapprove. Returns the new request id and pending "
            "status. Refuses if the requester IS the owner — they should "
            "edit the contact directly via update_contact."
        ),
        input_model=RequestChangeInput,
    ),
    "resolve_change_request": ToolSpec(
        name="resolve_change_request",
        description=(
            "Owner only: approve or disapprove a pending change request. "
            "Approve applies the requested change to the contact; "
            "disapprove leaves the contact untouched. Either way the "
            "request is closed with a timestamp + the resolver's id and "
            "an audit row is written. Optional note is shown to the "
            "requester."
        ),
        input_model=ResolveChangeRequestInput,
    ),
    "create_next_step": ToolSpec(
        name="create_next_step",
        description=(
            "Add a forward-looking todo to a contact's Next Steps log. "
            "Creates an in-app row AND a task on the OWNER's "
            "'DIN: Next Steps' Google Tasks list (title prefixed with "
            "the contact name). Use when the user says 'add a next "
            "step for Marcus to call next week, owner Jordan Blake' or "
            "similar. Resolve the owner's name to one of the three "
            "DIN team emails. Refuses if the contact is not visible "
            "to the caller, or if owner_email is not on the DIN team."
        ),
        input_model=CreateNextStepInput,
    ),
    "accept_satchel_charter": ToolSpec(
        name="accept_satchel_charter",
        description=(
            "Record the teammate's acceptance of the Satchel charter (the "
            "one-time consent that unlocks Satchel's web errands). Call "
            "ONLY after they explicitly agree — never infer consent."
        ),
        input_model=AcceptSatchelCharterInput,
    ),
    "satchel_web_check": ToolSpec(
        name="satchel_web_check",
        description=(
            "Satchel searches the PUBLIC WEB for one contact's missing "
            "details (title, employer, published email) — proposals with "
            "source URLs, nothing written. Requires the Satchel charter; "
            "works only on contacts the caller OWNS. On the user's yes, "
            "apply approved values via update_contact (empty fields only)."
        ),
        input_model=SatchelWebCheckInput,
    ),
    "satchel_org_scout": ToolSpec(
        name="satchel_org_scout",
        description=(
            "Satchel scouts an ORGANIZATION's public footprint for the "
            "right people for a stated purpose ('find who at X to invite "
            "to Y') — CANDIDATES with source URLs, nothing created. "
            "Requires the Satchel charter. Each approved person is then "
            "created via the normal create_contact intake, one at a time "
            "— never bulk-created."
        ),
        input_model=SatchelOrgScoutInput,
    ),
    "create_event": ToolSpec(
        name="create_event",
        description=(
            "Catalogue a DIN event under a stable catalog number "
            "(DIN-2026-001). Use for 'create an event', 'catalog the "
            "Mobile dinner'. Read the assigned catalog number back."
        ),
        input_model=CreateEventInput,
    ),
    "list_events": ToolSpec(
        name="list_events",
        description=(
            "List catalogued events with their catalog numbers, dates, "
            "and invite/attendance counts. Use for 'what events do we "
            "have', 'find the Mobile dinner'."
        ),
        input_model=ListEventsInput,
    ),
    "update_event": ToolSpec(
        name="update_event",
        description=(
            "Update a catalogued event (title, date, location, notes). "
            "NOTES REPLACE — for 'add X to the notes', read the current "
            "notes via list_events and send the merged text. The catalog "
            "number never changes."
        ),
        input_model=UpdateEventInput,
    ),
    "record_event_invite": ToolSpec(
        name="record_event_invite",
        description=(
            "Tie a contact to an event: Invited or Attended (Attended "
            "upgrades, never downgrades). 'We invited X to the dinner' / "
            "'X attended DIN-2026-001'. Resolve the contact id first."
        ),
        input_model=RecordEventInviteInput,
    ),
    "complete_next_step": ToolSpec(
        name="complete_next_step",
        description=(
            "Mark a next-step done. Only the step's owner OR the "
            "contact's owner can complete it; everyone else gets "
            "forbidden. Also marks the linked Google Tasks task "
            "complete on the owner's account, best-effort."
        ),
        input_model=CompleteNextStepInput,
    ),
    "transfer_contact": ToolSpec(
        name="transfer_contact",
        description=(
            "Move ownership of a contact to an DIN teammate. The "
            "current owner OR an admin may call this — admin bypass "
            "exists so a teammate's contacts can be reassigned when "
            "they leave the team. Immediate effect (no accept step on "
            "the receiving side). Writes an audit row capturing the "
            "old and new owner. Refuses if new_owner_email is not on "
            "the DIN team, if the contact doesn't exist, or if the "
            "new owner is already the current owner (no-op)."
        ),
        input_model=TransferContactInput,
    ),
    "create_google_task": ToolSpec(
        name="create_google_task",
        description=(
            "Drop a 'Talk to <Owner>' reminder into the CALLING USER's "
            "own Google Tasks, in a list named 'DIN: Talk to <Owner "
            "Name>'. The contact's owner is derived from contact_id; "
            "do not pass it. Use after answering a 'whose contact is "
            "this?' question and the user says yes to the offer. "
            "Refuses if the user IS the owner (they don't need a "
            "reminder to talk to themselves). Returns the task_id, "
            "list title, and owner name."
        ),
        input_model=CreateGoogleTaskInput,
    ),
}


def anthropic_tool_definitions() -> list[dict[str, Any]]:
    """Return the registry as a list of dicts ready for Anthropic's tools=."""
    return [spec.to_anthropic_dict() for spec in TOOL_REGISTRY.values()]
