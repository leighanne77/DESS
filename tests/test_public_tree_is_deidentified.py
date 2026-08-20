"""The publication gate: nothing private can merge, by construction.

WHY A GATE AND NOT A SCRUB. A scrub is a pass someone remembers to run; a
gate is a condition of merging. This tree is public and the same system
runs privately, so the contract is structural: the build fails if an
identifier that could belong to the private deployment appears anywhere
in tracked files.

WHY AN ALLOWLIST AND NOT A DENYLIST. A denylist of private names cannot
live in a public repository without publishing exactly what it protects —
and it would only ever catch what someone thought to list. Inverted:
every email domain in the tree must be `.fake` or carry a written reason
below, so an unanticipated real domain fails by default.

THE GATE EARNED ITS KEEP BEFORE IT EXISTED. Writing it surfaced a real
retired team domain and two plausible-and-real firm domains sitting in
test fixtures — exactly the class of leak a remembered scrub misses.

Layer 2 (optional, CI-armed): a pattern list supplied via the
PRIVATE_TREE_PATTERNS environment variable — set as a CI secret, never
committed — catches non-email identifiers (names, hosts) without
publishing them. Unset, that layer skips loudly rather than pretending
it ran.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from app.services.gov_detect import looks_like_gov_email

REPO = Path(__file__).resolve().parent.parent

#: Real domains that may appear, each with a written reason. Adding an
#: entry is a deliberate act — "the test was red" is not a reason.
ALLOWED_DOMAINS: dict[str, str] = {
    "example.com": "RFC 2606 reserved; can never belong to anyone.",
    "gmail.com": (
        "Subject matter: consumer-domain semantics under test — a fixture "
        "must be recognisably consumer for the assertion to mean anything. "
        "Also smtp.gmail.com as a default SMTP host in config."
    ),
}

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

#: Third-party manifests carry their authors' real contact details; the
#: gate governs OUR content, not vendored metadata.
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}

_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".ico", ".svg", ".woff", ".woff2", ".p8",
    ".pyc", ".map", ".lock",
}


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split("\n")
    files = []
    for name in filter(None, out):
        p = REPO / name
        if (
            p.name in _SKIP_NAMES
            or p.suffix.lower() in _SKIP_SUFFIXES
            or not p.is_file()
        ):
            continue
        files.append(p)
    return files


def test_every_email_domain_is_fake_or_has_a_written_reason():
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for match in _EMAIL.finditer(line):
                domain = match.group(1).lower()
                if domain.endswith(".fake") or domain in ALLOWED_DOMAINS:
                    continue
                # Government domains are the subject matter of the
                # gov-detection feature; the gate defers to the feature's
                # OWN classifier, so the two lists cannot drift apart.
                if looks_like_gov_email(f"x@{domain}"):
                    continue
                offenders.append(
                    f"{path.relative_to(REPO)}:{i}  {match.group(0)}"
                )
    assert not offenders, (
        "Email domains outside the fictional namespace, with no written "
        "reason. Either move the address to the fictional cast under the "
        ".fake TLD, or — if the domain is genuinely the subject matter — "
        "add it to ALLOWED_DOMAINS with a reason a reviewer would accept:"
        "\n\n" + "\n".join(f"  {o}" for o in offenders)
    )


def test_private_pattern_layer():
    """Layer 2: identifiers that are not email-shaped.

    The pattern list is supplied by CI as a secret (newline-separated,
    case-insensitive regular expressions) precisely so it never appears
    in this public tree. Locally and until the secret is set, this skips
    LOUDLY — a layer that silently pretends to run is worse than none.
    """
    raw = os.environ.get("PRIVATE_TREE_PATTERNS", "").strip()
    if not raw:
        pytest.skip(
            "PRIVATE_TREE_PATTERNS not set — layer 2 unarmed. Arm it with "
            "a CI secret; the list must never be committed here."
        )
    patterns = [
        re.compile(p, re.IGNORECASE) for p in raw.splitlines() if p.strip()
    ]
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pattern in patterns:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(REPO)}:{i}")
                    break
    assert not offenders, (
        "Private-deployment identifiers matched in tracked files "
        "(patterns withheld by design):\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


def test_the_fictional_cast_stays_fictional():
    """The seed dataset is the one place example people are minted, and
    every address in it lives under .fake — obviously unreal by TLD."""
    seed = (REPO / "scripts" / "seed_dummy_data.py").read_text(encoding="utf-8")
    # The fictional TEAM (alex, sam, jordan) rides example.com — RFC 2606
    # reserves it, so it is unownable by standard, which is the same
    # guarantee .fake gives by not existing.
    real = [
        m.group(0)
        for m in _EMAIL.finditer(seed)
        if not m.group(1).lower().endswith(".fake")
        and m.group(1).lower() != "example.com"
    ]
    assert not real, f"Real-looking addresses in the fictional cast: {real}"
