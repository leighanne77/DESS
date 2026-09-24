"""Policy engine v1 (harness slice 0–1) — the rulebook reader.

What matters here:
  - deny-by-default: unlisted tool or unknown agent → DENY
  - fail-closed: unreadable rulebook → DENY everything
  - registry parity: policies.yaml and TOOL_REGISTRY can never drift —
    every dispatchable tool must be governed, every governed tool must
    exist. This is the CI tripwire for "someone added a tool but forgot
    the policy" (and vice versa).
  - shadow vs enforce: shadow logs but never blocks; enforce blocks DENY.
"""

from pathlib import Path

import pytest

from app.services import policy
from app.services.policy import Verdict, evaluate
from app.services.tools import TOOL_REGISTRY


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    policy.reset_cache()
    yield
    policy.reset_cache()


# --- verdicts -----------------------------------------------------------


def test_allows_registered_tool_for_dess_chat() -> None:
    d = evaluate("dess-chat", "search_contacts")
    assert d.verdict is Verdict.ALLOW
    assert d.policy_version == 2


def test_delete_contact_requires_confirmation() -> None:
    assert evaluate("dess-chat", "delete_contact").verdict is Verdict.CONFIRM


def test_unlisted_tool_denied_by_default() -> None:
    d = evaluate("dess-chat", "drop_all_tables")
    assert d.verdict is Verdict.DENY
    assert "deny-by-default" in d.reason


def test_unknown_agent_denied() -> None:
    assert evaluate("rogue-agent", "search_contacts").verdict is Verdict.DENY


# --- fail-closed --------------------------------------------------------


def test_missing_policy_file_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "POLICY_PATH", Path("/nonexistent/policies.yaml"))
    d = evaluate("dess-chat", "search_contacts")
    assert d.verdict is Verdict.DENY
    assert d.policy_version is None
    assert "fail-closed" in d.reason


def test_malformed_policy_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "policies.yaml"
    bad.write_text("just a string, not a mapping")
    monkeypatch.setattr(policy, "POLICY_PATH", bad)
    assert evaluate("dess-chat", "search_contacts").verdict is Verdict.DENY


# --- registry parity (the anti-drift tripwire) ---------------------------


def test_every_dispatchable_tool_is_governed() -> None:
    """A tool in TOOL_REGISTRY but absent from policies.yaml would be
    silently DENIED the day enforcement flips — catch it in CI instead."""
    for tool in TOOL_REGISTRY:
        d = evaluate("dess-chat", tool)
        assert d.verdict in (
            Verdict.ALLOW,
            Verdict.CONFIRM,
        ), f"{tool} is dispatchable but not in policies.yaml for dess-chat"


def test_every_governed_tool_is_dispatchable() -> None:
    """A tool in policies.yaml but not in TOOL_REGISTRY is a stale policy
    entry — the rulebook must describe reality."""
    loaded = policy._load_policy()
    assert loaded is not None
    tools = loaded["agents"]["dess-chat"]["tools"]
    governed = set(tools.get("allow") or []) | set(tools.get("confirm") or [])
    stale = governed - set(TOOL_REGISTRY)
    assert not stale, f"policies.yaml lists unknown tools: {sorted(stale)}"


# --- shadow vs enforce in the dispatcher ---------------------------------


def test_shadow_mode_never_blocks(db, user_factory) -> None:
    """POLICY_ENFORCE=false (default): a DENY verdict is logged, not raised.
    We prove it by dispatching a real (allowed) call the normal way — and
    separately asserting enforcement is off in settings."""
    from app.config import get_settings
    from app.services.tool_dispatch import dispatch_tool_call

    assert get_settings().policy_enforce is False
    user = user_factory()
    result = dispatch_tool_call("search_contacts", {"query": "nobody"}, user, db)
    assert "results" in result


def test_enforce_mode_blocks_denied_agent(
    db, user_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With enforcement on, an agent outside its allowlist is refused
    BEFORE any handler runs (unknown agents may dispatch nothing)."""
    from app.config import get_settings
    from app.services.tool_dispatch import ToolDispatchError, dispatch_tool_call

    settings = get_settings()
    monkeypatch.setattr(settings, "policy_enforce", True)
    user = user_factory()
    with pytest.raises(ToolDispatchError, match="Policy denied"):
        dispatch_tool_call(
            "search_contacts", {"query": "x"}, user, db, agent_id="rogue-agent"
        )


# --- slice 3: kill switch + agent identity stamping ----------------------


def test_kill_switch_blocks_even_in_shadow_mode(
    db, user_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enabled:false is an operator action — it HARD-blocks the agent
    even with POLICY_ENFORCE=false (shadow never softens a kill switch)."""
    from app.config import get_settings
    from app.services.tool_dispatch import ToolDispatchError, dispatch_tool_call

    disabled = tmp_path / "policies.yaml"
    disabled.write_text(
        "version: 99\n"
        "agents:\n"
        "  dess-chat:\n"
        "    enabled: false\n"
        "    tools:\n"
        "      allow: [search_contacts]\n"
    )
    monkeypatch.setattr(policy, "POLICY_PATH", disabled)
    assert get_settings().policy_enforce is False  # shadow mode

    d = evaluate("dess-chat", "search_contacts")
    assert d.verdict is Verdict.DENY
    assert d.hard is True
    assert "kill switch" in d.reason

    user = user_factory()
    with pytest.raises(ToolDispatchError, match="kill switch"):
        dispatch_tool_call("search_contacts", {"query": "x"}, user, db)


def test_audit_rows_stamped_with_agent_identity(db, user_factory) -> None:
    """Every audit row written inside a dispatch carries agent_id +
    policy_version — attribution without touching the 20+ call sites."""
    from sqlalchemy import select

    from app.models import AuditLog
    from app.services.tool_dispatch import dispatch_tool_call

    user = user_factory()
    result = dispatch_tool_call(
        "create_contact",
        {
            "name": "Stamped Person",
            "fly_status": "Unknown",
            "is_private": True,
        },
        user,
        db,
    )
    contact_id = result["created"]["id"]
    row = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "create_contact", AuditLog.target_id == contact_id
        )
    ).first()
    assert row is not None
    assert row.payload_metadata["agent_id"] == "dess-chat"
    assert row.payload_metadata["policy_version"] == 2


def test_agent_scope_clears_after_dispatch(db, user_factory) -> None:
    """Identity never leaks past the dispatch — outside a scope,
    current() is None (plain human-driven REST writes stay unstamped)."""
    from app.services import agent_context
    from app.services.tool_dispatch import dispatch_tool_call

    user = user_factory()
    dispatch_tool_call("search_contacts", {"query": "x"}, user, db)
    assert agent_context.current() is None
