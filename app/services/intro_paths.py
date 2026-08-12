"""Warm-introduction engine — deterministic scoring (Phase 5 Slice 2).

Pure functions, no database, no model. This is the trust-critical core:
the math that decides whether a path is usable and how warm it is lives
here, in code, auditable and unit-tested — Claude never decides who's
blocklisted or how warm a contact is. Slice 3 (the recursive-CTE
pathfinder) builds candidate paths from the `relationships` graph and
hands them to `rank_paths`; this file does not touch SQLAlchemy.

A path answers three questions (see Docs/Phase_5_Warm_Intro_Engine.md):

1. GATES — can we use this path at all? A path is discarded if any
   intermediary is blocklisted (fly_status='Off Fly List') or not opted
   in (opt_in_status != 'APPROVED'). Gates delete, they don't score.
2. OUR-SIDE WARMTH (affinity) — how well do we know the person we'd
   actually contact, i.e. the FIRST intermediary. Mapped from fly_status.
3. THEIR-SIDE CONNECTION — how well does each go-between know the next
   node, ending at the target. Sector overlap + shared_history per edge.

    path_score = affinity(first intermediary)
               * product(connection over each edge to the target)
               / degrees_of_separation

Geography (same metro) is a term in `connection` — see W_GEO. Everything
here is a tunable constant on purpose; reweight the W_* values freely.
"""

from __future__ import annotations

from dataclasses import dataclass

# fly_status tiers (the values, their warmth, and the blocklisted tier)
# live in one place so they can't drift across the engine, the tool
# schema, and search ordering. See app/services/fly_status.py.
from app.services.fly_status import BLOCKLIST_FLY_STATUS, affinity_for

# --- Tunable weights ---------------------------------------------------

# Coarse shared-history strength on an edge → [0, 1].
SHARED_HISTORY_WEIGHT: dict[str, float] = {"none": 0.0, "some": 0.5, "strong": 1.0}

# Connection-score weights — they sum to 1.0. Tunable.
W_SECTOR: float = 0.45
W_SHARED_HISTORY: float = 0.35
W_GEO: float = 0.20

# Gate constant. BLOCKLIST_FLY_STATUS is imported above (shared).
OPT_IN_APPROVED: str = "APPROVED"


# --- Value objects (ORM-free so the engine stays pure) -----------------


@dataclass(frozen=True)
class ContactNode:
    """The subset of a contact the engine needs. Slice 3 builds these
    from `Contact` rows; tests build them directly."""

    contact_id: int
    name: str
    fly_status: str
    opt_in_status: str
    # Retired people are never offered as intermediaries — asking someone
    # who has left the field to make a working introduction is exactly the
    # kind of judgment the gates exist to encode. (A retired TARGET is
    # allowed: naming the person is the explicit ask.)
    retired: bool = False
    sectors: tuple[str, ...] = ()
    metro: str = ""


@dataclass(frozen=True)
class IntroPath:
    """A candidate route from the requester to `target`.

    `intermediaries` are the people we'd route through, ordered from the
    requester side (intermediaries[0] is whom we actually contact).
    `hop_histories` is the shared_history of each edge along the chain
    [intermediaries..., target] — exactly one per edge, so
    len(hop_histories) == len(intermediaries).
    """

    intermediaries: tuple[ContactNode, ...]
    target: ContactNode
    hop_histories: tuple[str, ...]


@dataclass(frozen=True)
class ScoredPath:
    """Result of scoring one IntroPath. `gated_reason` is None for a
    usable path; otherwise the path is excluded and `score` is 0.0."""

    path: IntroPath
    score: float
    affinity: float
    connection: float
    degrees: int
    gated_reason: str | None


# --- Primitives --------------------------------------------------------


def affinity(fly_status: str) -> float:
    """Our-side warmth from a contact's fly_status, in [0, 1]. Unknown
    statuses fall back to 0.0 (treated as cold, never raises). Thin alias
    over the shared `affinity_for` so the weights live in one place."""
    return affinity_for(fly_status)


def gate_reason(
    fly_status: str, opt_in_status: str, retired: bool = False
) -> str | None:
    """Return why this contact can't be a node on an intro path, or None
    if it's usable. Blocklist first, then outreach consent, then
    retirement (mostly-hidden posture)."""
    if fly_status == BLOCKLIST_FLY_STATUS:
        return "blocklisted (Off Fly List)"
    if opt_in_status != OPT_IN_APPROVED:
        return f"opt-in {opt_in_status.lower()}"
    if retired:
        return "retired"
    return None


def sector_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Jaccard overlap of two sector sets, in [0, 1]. Case-insensitive.
    Returns 0.0 if either side has no sectors (no signal, not a match)."""
    set_a = {s.strip().lower() for s in a if s and s.strip()}
    set_b = {s.strip().lower() for s in b if s and s.strip()}
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def shared_history_weight(value: str) -> float:
    """Map a shared_history label to [0, 1]; unknown labels → 0.0."""
    return SHARED_HISTORY_WEIGHT.get(value, 0.0)


def is_geographically_close(a_metro: str, b_metro: str) -> bool:
    """True if both contacts are in the same metro (case-insensitive).
    Empty/unknown metro on either side → not close (no signal)."""
    a = a_metro.strip().lower()
    b = b_metro.strip().lower()
    return bool(a) and a == b


def connection_strength(
    a_sectors: tuple[str, ...],
    b_sectors: tuple[str, ...],
    shared_history: str,
    a_metro: str = "",
    b_metro: str = "",
) -> float:
    """Their-side connection across a single edge a→b, in [0, 1]:
    weighted sector overlap + shared history + same-metro geography."""
    geo = 1.0 if is_geographically_close(a_metro, b_metro) else 0.0
    return (
        W_SECTOR * sector_overlap(a_sectors, b_sectors)
        + W_SHARED_HISTORY * shared_history_weight(shared_history)
        + W_GEO * geo
    )


# --- Path scoring ------------------------------------------------------


def score_path(path: IntroPath) -> ScoredPath:
    """Score one candidate path. Gates first (any blocklisted / non-opted
    intermediary discards the whole path); then affinity × connection ÷
    degrees. A path with no intermediaries is invalid → gated."""
    if not path.intermediaries:
        return ScoredPath(path, 0.0, 0.0, 0.0, 0, "no intermediary")

    # Gate every intermediary we'd route through. The target itself is
    # not gated — we don't pass *through* the person we want to reach.
    for node in path.intermediaries:
        reason = gate_reason(node.fly_status, node.opt_in_status, node.retired)
        if reason is not None:
            return ScoredPath(
                path, 0.0, 0.0, 0.0, len(path.intermediaries), f"{node.name}: {reason}"
            )

    aff = affinity(path.intermediaries[0].fly_status)

    # Walk the chain [intermediaries..., target], multiplying each edge's
    # connection. hop_histories[i] is the edge from chain[i] to chain[i+1].
    chain: list[ContactNode] = [*path.intermediaries, path.target]
    connection = 1.0
    for i in range(len(path.intermediaries)):
        connection *= connection_strength(
            chain[i].sectors,
            chain[i + 1].sectors,
            path.hop_histories[i],
            chain[i].metro,
            chain[i + 1].metro,
        )

    degrees = len(path.intermediaries)
    score = aff * connection / degrees
    return ScoredPath(path, score, aff, connection, degrees, None)


def rank_paths(paths: list[IntroPath]) -> list[ScoredPath]:
    """Score every candidate, drop the gated ones, and return the usable
    paths best-first. Ties break toward fewer hops, then the first
    intermediary's name for stable output."""
    scored = [score_path(p) for p in paths]
    usable = [s for s in scored if s.gated_reason is None]
    usable.sort(key=lambda s: (-s.score, s.degrees, s.path.intermediaries[0].name))
    return usable
