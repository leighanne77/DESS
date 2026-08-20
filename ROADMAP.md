# Roadmap — advance copy

*One item, published before it lands. This is the next major slice for the
system behind this tree, shared in advance because the design says more about
the engineering than the finished feature will. Details will shift in the
build; the boundaries below are the commitments.*

## The crew: one assistant becomes several agents

Today this repository registers **one** agent (`dess-chat` in
`app/policies.yaml`) — and the registry's own description says the quiet
part: *"the same pattern scales to additional agents by adding entries
here."* The crew slice is that sentence made real.

**What changes.** The assistant's bounded discovery lanes — the web check,
the org scout, the bulk import — graduate from tools *called by* the chat
agent into agents *of their own*: each with its own registry entry, its own
allowlist, its own kill switch, and its own audit identity, coordinated
over an agent-to-agent protocol rather than a shared prompt.

**What deliberately does not change:**

- **`policies.yaml` stays the single authority.** It was written as a live
  per-agent registry from day one; the crew is its graduation, not its
  replacement. Adding an agent is adding an entry — deny-by-default,
  version-bumped, test-pinned.
- **The consent charter stays the human gate at the boundary.** A crew can
  coordinate work; it cannot grant itself permission. The standing charter
  covers scheduled runs; a human yes covers every write, exactly as now.
- **No LLM planner in the trust path.** Agents may be many; the decisions
  about visibility, permission, and scoring stay in deterministic code.
  Orchestration is declarative and light — nondeterminism contained inside
  contract-bounded steps, not eliminated.

**First duty handed off: the bulk web-check sweep.** The engine already
takes a capped list of contacts per run; the crew adds the orchestrator and
a combined review pass. Chosen first because it is the lane where the
harness is already strongest — hard search caps, source-cited proposals,
nothing written without review.

**Riding along: model failover at the one seam.** Every model call funnels
through a single choke point, so a second model family slots in behind it —
quota and billing errors replay against the fallback, with every audit row
stamped by which model answered. One seam, not a scattering of retries.

**The horizon it builds toward: local-first.** The agent-to-agent seams and
the authority registry are designed to carry to local hardware unchanged —
the long-game test applied to every integration choice here is *"does this
bind us harder to one cloud?"*

---

*Sequencing, dates, and the private deployment's specifics are not
published. What is published is checkable: the registry, the charter gate,
the confirm tokens, and the discovery lanes named above are all in this
repository today.*
