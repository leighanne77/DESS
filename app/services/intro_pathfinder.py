"""Warm-introduction pathfinder (Phase 5 Slice 3) — the DB-touching half.

Builds candidate introduction paths to a target by walking the
`relationships` graph (up to 2 hops, edges treated as bidirectional for
reachability), then hands them to the pure scorer
(`intro_paths.rank_paths`). The pure engine stays DB-free; all SQLAlchemy
lives here.

**Privacy composes with the gate.** We only ever load contacts the
requester can *see* (`visible_contacts_query`), so a path can never route
through — or reveal — a contact the requester isn't allowed to see. On top
of that, `rank_paths` drops any path through a blocklisted (`Off Fly List`)
or non-`APPROVED` intermediary. So the answer respects, in order: the
three-tier privacy filter, then the blocklist, then outreach consent.

**Why in-memory, not a recursive CTE.** For a team-sized CRM, loading the
visible contacts + the edges among them and enumerating 1- and 2-hop chains
in Python is simpler and far more testable than recursive SQL. If the graph
ever gets large, push the walk into a `WITH RECURSIVE` query — the scoring
and the interface don't change.

**Scoping.** When the requester is linked to their own contact record
(`contacts.user_id`, set by email-match), paths are scoped to the
requester's *own* relationships: the first intermediary — whom we'd
actually reach out to — must be someone the requester directly knows, and
the requester is never routed through or to. When the requester has no
linked contact node, we fall back to firm-wide reachability over all
visible contacts (the original v1 behavior). The first intermediary in a
path is whom we'd actually reach out to.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Relationship, User
from app.services.intro_paths import ContactNode, IntroPath, ScoredPath, rank_paths
from app.services.privacy import visible_contacts_query


@dataclass(frozen=True)
class IntroPathsResult:
    """`target` is None when the target isn't visible/found; `paths` are the
    ranked, usable routes (empty if there's no target or no warm path)."""

    target: ContactNode | None
    paths: list[ScoredPath]


def _node(c: Contact) -> ContactNode:
    return ContactNode(
        contact_id=c.id,
        name=c.name,
        fly_status=c.fly_status,
        opt_in_status=c.opt_in_status,
        sectors=tuple(c.sectors or ()),
        metro=c.metro or "",
        retired=c.retired,
    )


def find_intro_paths(
    db: Session, requester: User, target_id: int, *, max_results: int = 5
) -> IntroPathsResult:
    """Find the warmest 1–2 hop introduction paths to `target_id` that the
    requester is allowed to see, best-first."""
    # Universe: contacts visible to the requester (privacy at the query layer).
    visible: dict[int, Contact] = {
        c.id: c for c in db.scalars(visible_contacts_query(requester))
    }
    target = visible.get(target_id)
    if target is None:
        return IntroPathsResult(target=None, paths=[])

    # The requester's own contact node, when they're linked to a contact
    # record we can see. Present → scope paths to the requester's own
    # relationships; absent (unlinked user) → firm-wide v1 fallback.
    requester_contact_id = db.scalar(
        select(Contact.id).where(
            Contact.user_id == requester.id, Contact.deleted_at.is_(None)
        )
    )
    if requester_contact_id is not None and requester_contact_id not in visible:
        requester_contact_id = None

    # You can't be introduced to yourself.
    if requester_contact_id is not None and target_id == requester_contact_id:
        return IntroPathsResult(target=_node(target), paths=[])

    # Adjacency over visible contacts only; edges are undirected for reach.
    adj: dict[int, list[tuple[int, str]]] = {}
    for e in db.scalars(select(Relationship).where(Relationship.deleted_at.is_(None))):
        if e.from_contact_id in visible and e.to_contact_id in visible:
            adj.setdefault(e.from_contact_id, []).append(
                (e.to_contact_id, e.shared_history)
            )
            adj.setdefault(e.to_contact_id, []).append(
                (e.from_contact_id, e.shared_history)
            )

    target_node = _node(target)
    candidates: list[IntroPath] = []

    # 1-hop: A — T   (A directly knows the target)
    for a_id, hist_at in adj.get(target_id, []):
        if a_id == target_id:
            continue
        candidates.append(
            IntroPath(
                intermediaries=(_node(visible[a_id]),),
                target=target_node,
                hop_histories=(hist_at,),
            )
        )

    # 2-hop: A — B — T   (A is whom we contact; B connects A to the target)
    for b_id, hist_bt in adj.get(target_id, []):
        if b_id == target_id:
            continue
        for a_id, hist_ab in adj.get(b_id, []):
            if a_id in (target_id, b_id):
                continue
            candidates.append(
                IntroPath(
                    intermediaries=(
                        _node(visible[a_id]),
                        _node(visible[b_id]),
                    ),
                    target=target_node,
                    hop_histories=(hist_ab, hist_bt),
                )
            )

    # Scope to the requester's own relationships: the person we'd reach out
    # to (the first intermediary) must be someone the requester directly
    # knows, and the requester is never a node on the path. Unlinked
    # requester → no filter (firm-wide).
    if requester_contact_id is not None:
        own_neighbors = {nbr_id for nbr_id, _ in adj.get(requester_contact_id, [])}
        candidates = [
            c
            for c in candidates
            if c.intermediaries[0].contact_id in own_neighbors
            and requester_contact_id not in {m.contact_id for m in c.intermediaries}
        ]

    ranked = rank_paths(candidates)
    return IntroPathsResult(target=target_node, paths=ranked[:max_results])
