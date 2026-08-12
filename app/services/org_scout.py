"""Satchel org scout — find the right people AT an organization.

Owner ask 2026-08-12. The third act of Satchel's web work, and a genuinely
different one: web_enrich fills gaps for people already in the CRM; this
finds people who are NOT in it yet — "who at ONE Bow River should we
invite to the maritime briefing?" — by searching an organization's public
footprint for the roles that fit a stated purpose.

The guardrails carry over from web_enrich, adapted to discovery:

* **Cost.** One scout = one model call with a hard search cap
  (MAX_SEARCHES), a bounded candidate list (MAX_CANDIDATES), and it only
  runs when a teammate asks. Nothing scouts on its own.
* **Privacy — on the way OUT.** Only the organization name and the stated
  purpose are sent to the search. No CRM contact data leaves at all —
  there is no contact yet.
* **Accuracy — on the way IN.** Candidates are model judgment over search
  results, so every candidate carries source URLs, contact details are
  published-only (never constructed from a naming pattern), and a short
  list beats a padded one. Candidates are PROPOSALS: nothing enters the
  CRM except through the normal create_contact intake — three questions,
  one person at a time, on the user's explicit yes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.llm import call_claude
from app.services.web_enrich import _parse_json_blob, count_searches

logger = logging.getLogger(__name__)

# --- Cost ceilings ---------------------------------------------------------
# A scout ranges wider than a per-person lookup (team pages, leadership
# pages, press, conference agendas), so it gets a slightly deeper search
# budget — but exactly one bounded call per ask.
MAX_SEARCHES = 5
MAX_CANDIDATES = 8

_SYSTEM = (
    "You scout an ORGANIZATION's public footprint to find the right people "
    "for a stated purpose, for a dual-use investor network's contact "
    "database.\n"
    "Rules:\n"
    "1. The user gives an organization and what they need people FOR "
    "(invite to a briefing, discuss a technology, an introduction). Find "
    "the people whose published role fits that purpose — leadership pages, "
    "team pages, press releases, filings, conference agendas.\n"
    "2. Report ONLY people a source actually names in a role at this "
    "organization. Never guess, never infer from a similar org name, and "
    "skip anyone you cannot tie to the organization with confidence. A "
    "short, right list beats a padded one; an empty list is a valid "
    "answer.\n"
    "3. CONTACT DETAILS (email, phone) are held to the highest bar: give "
    "them only when an authoritative page publishes them for this exact "
    "person. Never construct an email from a naming pattern, and never use "
    "a generic info@ or switchboard line as a person's contact detail. "
    "Most candidates will and should have null contact details.\n"
    "4. People move jobs: prefer current, dated sources, and if a source "
    "looks stale, say so in that candidate's why.\n"
    "5. Prefer the organization's own site, government and trade sources.\n"
    f"6. At most {MAX_CANDIDATES} candidates, best fit first.\n"
    'Reply with ONLY this JSON: {"candidates": [{"name": <string>, '
    '"title": <string|null>, "company_name": <string|null>, '
    '"email": <string|null>, "office_phone": <string|null>, '
    '"why": <one line: how their role fits the purpose>, '
    '"sources": [<url>, ...]}, ...], "note": <short string|null>}\n'
    "company_name is the employer as published (a subsidiary or division "
    "counts — name the one the source names). sources must be the URLs you "
    "actually used, per candidate. note is a one-line caveat about the "
    "whole scout when needed, else null. No prose, no code fences."
)


@dataclass
class ScoutCandidate:
    """One person the scout surfaced, with citations. Not a contact —
    a proposal that may become one, via the normal intake."""

    name: str
    title: str | None = None
    company_name: str | None = None
    email: str | None = None
    office_phone: str | None = None
    why: str | None = None
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "company_name": self.company_name,
            "email": self.email,
            "office_phone": self.office_phone,
            "why": self.why,
            "sources": self.sources,
        }


def _search_tool() -> dict[str, Any]:
    """Server-side web search, capped per scout (see web_enrich for why
    max_uses is the lever that matters)."""
    return {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": MAX_SEARCHES,
    }


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


async def scout_org(
    organization: str,
    looking_for: str,
    *,
    on_tokens: Any = None,
) -> tuple[list[ScoutCandidate], int, str | None]:
    """One bounded scout. Returns (candidates, searches_run, note) —
    searches feed the audit row so every run's spend is visible."""
    try:
        message = await call_claude(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Organization: {organization}\n"
                        f"Looking for people to: {looking_for}\n"
                        "Find the right people at this organization for "
                        "that purpose."
                    ),
                }
            ],
            system=_SYSTEM,
            tools=[_search_tool()],
            on_tokens=on_tokens,
            max_tokens=3000,
        )
    except Exception:
        logger.exception("org scout failed for %r", organization)
        return [], 0, None

    searches = count_searches(message)
    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
    data = _parse_json_blob(text)

    candidates: list[ScoutCandidate] = []
    for raw in (data.get("candidates") or [])[:MAX_CANDIDATES]:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"))
        if not name:
            continue  # a candidate without a name is not a candidate
        sources = [
            s.strip()
            for s in (raw.get("sources") or [])
            if isinstance(s, str) and s.strip().startswith("http")
        ]
        candidates.append(
            ScoutCandidate(
                name=name,
                title=_clean(raw.get("title")),
                company_name=_clean(raw.get("company_name")),
                email=_clean(raw.get("email")),
                office_phone=_clean(raw.get("office_phone")),
                why=_clean(raw.get("why")),
                sources=sources[:5],
            )
        )
    return candidates, searches, _clean(data.get("note"))
