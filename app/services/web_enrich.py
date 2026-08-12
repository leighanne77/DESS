"""Satchel web lookup — fill contact gaps from public sources.

The public-web enrichment lane: asks Claude to search the public web
for a person's job title and employer, and brings back proposals with
the URLs they came from.

Deliberately narrow, for three separate reasons:

* **Cost.** Web search is metered per query, so every lever here is a cap:
  at most MAX_CONTACTS people per run, at most MAX_SEARCHES_PER_CONTACT
  queries each, and a bounded number in flight at once. Worst case per run
  is a known, small number of searches — it can't fan out across a
  1,000-row import. It is also opt-in per run: nothing searches on its own.
* **Privacy — on the way OUT.** Only the person's NAME and COMPANY are sent
  to the search; never their email, phone, or notes. Finding someone's
  published work email is fair game, but handing the address book's copy of
  it to a search engine is a different act, and this does not do that.
* **Accuracy — on the way IN.** This is model judgment over search
  results. So every proposed
  value carries the source URL it came from, nothing is written without
  review, and the prompt is explicit that a blank beats a guess. Contact
  details (email, phones) are held to that bar hardest: a wrong number is
  worse than a missing one, so a source must actually state it.

Proposals are review-first: nothing is written by the search itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.llm import call_claude

logger = logging.getLogger(__name__)

# --- Cost ceilings ---------------------------------------------------------
# Worst case per run = MAX_CONTACTS * MAX_SEARCHES_PER_CONTACT queries.
# At the current metered rate that is a few cents; the per-user daily token
# budget (app/routers/chat) remains the backstop for the token side.
MAX_CONTACTS = 10
MAX_SEARCHES_PER_CONTACT = 3
# How many lookups run at once. Keeps a run to roughly half a minute
# without opening an unbounded number of concurrent model calls.
CONCURRENCY = 5

# What a web lookup may propose. Contact details are included because a
# published work email or desk line is often the exact gap a spreadsheet
# leaves — but they carry the strictest sourcing rule in the prompt below.
WEB_FIELDS: tuple[str, ...] = (
    "title",
    "company_name",
    "email",
    "office_phone",
    "cell_phone",
)

_SYSTEM = (
    "You research a business contact using web search, for a "
    "dual-use investor network's contact database.\n"
    "Rules:\n"
    "1. Search for the person. Use the company name to disambiguate.\n"
    "2. Report ONLY what a source actually states. Never guess, never infer "
    "from a similar name, and never fill a field you did not find.\n"
    "3. If you cannot find the specific person with confidence — including "
    "when several people share the name — return nulls. A blank is correct "
    "and useful; a wrong answer is not.\n"
    "4. CONTACT DETAILS (email, phones) are held to the highest bar: give "
    "them only from an authoritative page that publishes them for this "
    "exact person — a company team page, an official directory, a press "
    "release, a filing. Never construct an email from a naming pattern, and "
    "never carry over a colleague's or a generic company address. A "
    "switchboard or info@ line is not this person's contact detail.\n"
    "5. Prefer a company's own site, government and trade sources.\n"
    'Reply with ONLY this JSON: {"title": <string|null>, "company_name": '
    '<string|null>, "email": <string|null>, "office_phone": <string|null>, '
    '"cell_phone": <string|null>, "sources": [<url>, ...], '
    '"note": <short string|null>}\n'
    "sources must be the URLs you actually used. note is a one-line caveat "
    "when you are unsure, else null. No prose, no code fences."
)


@dataclass
class WebProposal:
    """One contact's proposed web-sourced fill, with its citations."""

    contact_id: int
    contact_name: str
    fields: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    note: str | None = None
    matched_on: str = "web"

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "fields": self.fields,
            "sources": self.sources,
            "note": self.note,
            "matched_on": self.matched_on,
        }


def _search_tool() -> dict[str, Any]:
    """The server-side web-search tool, capped per call.

    max_uses is the precise cost lever: it bounds queries per lookup, and
    keeping it small also keeps the request under the server-side tool loop
    limit, so a lookup never comes back paused mid-turn.
    """
    return {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": MAX_SEARCHES_PER_CONTACT,
    }


def _parse_json_blob(text: str) -> dict[str, Any]:
    """Parse the model's reply, tolerating stray prose or fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def count_searches(message: Any) -> int:
    """How many web queries a reply actually ran — the billable unit."""
    total = 0
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", "") == "server_tool_use":
            if getattr(block, "name", "") == "web_search":
                total += 1
    return total


async def _lookup_one(
    contact: Any, gaps: list[str], on_tokens: Any
) -> tuple[WebProposal | None, int]:
    """One person's lookup. Returns (proposal or None, searches run)."""
    # Privacy: name + company only. Never the email, phone, or notes.
    who = contact.name
    if contact.company_name:
        who = f"{who} at {contact.company_name}"
    try:
        message = await call_claude(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Research this business contact: {who}. Find their "
                        "current job title, employer, and any contact details "
                        "an authoritative page publishes for them."
                    ),
                }
            ],
            system=_SYSTEM,
            tools=[_search_tool()],
            on_tokens=on_tokens,
            max_tokens=2000,
        )
    except Exception:
        logger.exception("web lookup failed for contact %s", contact.id)
        return None, 0

    searches = count_searches(message)
    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
    data = _parse_json_blob(text)

    fills: dict[str, str] = {}
    for name in WEB_FIELDS:
        if name not in gaps:
            continue  # never propose for a field that already has a value
        value = _clean(data.get(name))
        if value:
            fills[name] = value
    if not fills:
        return None, searches

    sources = [
        s.strip()
        for s in (data.get("sources") or [])
        if isinstance(s, str) and s.strip().startswith("http")
    ]
    return (
        WebProposal(
            contact_id=contact.id,
            contact_name=contact.name,
            fields=fills,
            sources=sources[:5],
            note=_clean(data.get("note")),
        ),
        searches,
    )


async def propose_from_web(
    contacts: list[Any],
    gaps_by_id: dict[int, list[str]],
    *,
    on_tokens: Any = None,
) -> tuple[list[WebProposal], int, int]:
    """Look up the given contacts on the web, bounded by the caps above.

    Returns (proposals, contacts_checked, searches_run) — the last two feed
    the audit row so the spend of every run is visible after the fact.
    """
    # Only people with a web-fillable gap, and never more than the cap.
    eligible = [
        c for c in contacts if any(f in gaps_by_id.get(c.id, []) for f in WEB_FIELDS)
    ][:MAX_CONTACTS]
    if not eligible:
        return [], 0, 0

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _guarded(contact: Any) -> tuple[WebProposal | None, int]:
        async with semaphore:
            return await _lookup_one(contact, gaps_by_id.get(contact.id, []), on_tokens)

    results = await asyncio.gather(*(_guarded(c) for c in eligible))
    proposals = [p for p, _ in results if p is not None]
    searches = sum(n for _, n in results)
    return proposals, len(eligible), searches


def missing_fields(contact: Any) -> list[str]:
    """Which web-fillable fields are empty on this contact, stable order."""
    return [f for f in WEB_FIELDS if not getattr(contact, f, None)]
