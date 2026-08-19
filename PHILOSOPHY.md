# How this system is built

The operating principles behind DESS — for the human reader.
([`CLAUDE.md`](CLAUDE.md) is the companion file: the same discipline
expressed as enforceable instructions to a coding agent.) The private
deployment this repository mirrors runs under a fuller operator–agent
working agreement; this document is the portable core of it.

## The model proposes; code decides

There is no LLM in the trust path. The model translates requests and
narrates answers — deterministic code decides who is visible, what is
permitted, and how an introduction path is scored. Prompts are
suggestions, and suggestions are not access control.

*Seen here:* `app/services/privacy.py`, `policy.py`, `intro_paths.py` —
and the dispatch loop that lets the model call tools but never skip the
policy check between intention and effect.

## Evidence over confidence

Anything automated that asserts a fact must carry its source — a URL and
a quote, or the matched text that produced a suggestion. Never a bare
confidence score: a `0.92` can only be trusted, while a quoted company
name can be *checked*, and the reviewer dismissing a wrong suggestion at
a glance is the mechanism that keeps review fast enough to happen.

*Seen here:* the web-enrichment lanes return proposals with source URLs;
nothing is written until a person accepts.

## Contracts over vigilance

When a convention can be checked mechanically, it becomes a test in the
same commit — because a convention is a bug that hasn't shipped yet.
Schema drift between models and migrations fails the build. A class of
mistake, once made, gets a test that makes it unrepeatable rather than a
document asking people to be careful.

*Seen here:* the policy registry is version-pinned by tests; the eval
suite pins prompt-injection resistance and vocabulary rules.

## Gates proportional to trust — and conditional, never constant

A stranger's form submission gets a review queue. A teammate's routine
edit gets no ceremony at all. An agent's write is always a proposal. And
a gate that fires on every action is worse than no gate — by the
twentieth confirmation, people click through, and the gate is now
manufacturing the false confidence it was meant to prevent. The quiet
path must stay quiet for the checks on the loud path to mean anything.

*Seen here:* destructive operations take a server-side two-step with
signed, expiring confirm tokens; ordinary reads and edits take nothing.

## Right-sized deliberately, with the revisit trigger written down

PostgreSQL throughout. Spark was rejected as over-scaled for the data
volume. A graph database was evaluated for the introduction engine and
deferred — the relationship graph is walked in memory, bounded at two
hops, because at team scale that is simpler, fully testable, and one
less system to secure. Every deferral carries its written trigger (for
the graph store: path queries straining into millions of edges), so a
future team can overturn the decision on evidence rather than fashion —
and so restraint reads as discipline instead of omission.

## Reversibility is a design property

Merging two records keeps both: the absorbed row is soft-deleted with a
pointer to its survivor, conflicting values are written down rather than
discarded, and every fold can be read back afterwards. A merge is a
judgement, and judgements are sometimes wrong — the system's job is to
make being wrong cheap, not impossible.

## Defaults are not answers

A required field whose options include "Unknown" collects ceremony, not
data — the escape hatch just gets selected out loud. So: never ask at
creation time what the creator cannot know; move the question to where
the answer exists; and keep a value's provenance, because "General,
considered" and "General, nobody decided" must not be the same fact.

## Records are honest, or they are worse than nothing

A dated answer that later changes gets a correction ledger entry, not a
silent rewrite. A report that begins recording on a given day says so,
so absence of data is never mistaken for absence of activity. Pages
retire; records never do. And status comes from the commit log, not from
the plan — a plan that answers confidently after it has drifted is more
dangerous than no plan at all.

---

*None of this eliminates nondeterminism — it contains it. The model is
free inside contract-bounded steps and powerless outside them, and every
boundary is one a test can hold.*
