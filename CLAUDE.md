# DESS — agent contract

Instructions for any coding agent working in this repository. Every rule
here is enforceable *inside this repo* — by a test, a config file, or a
grep — because an instruction an agent cannot verify is an instruction it
will eventually ignore.

## 1. The de-identification contract (the cardinal rule)

This is a public, scrubbed copy of a private production system. The scrub
is a one-way door:

- **Never introduce a real person, firm, email domain, or infrastructure
  identifier.** All example people come from the fictional cast in
  `scripts/seed_dummy_data.py`. If you need a new example person, add them
  to the cast — obviously fake, never plausible-and-real.
- **Never reference the private deployment** — its name, its domains, its
  service accounts, its team. If you find such a reference, removing it is
  always in scope, whatever you were asked to do.
- Check before you commit: `git grep -i` for whatever the private thing
  would be called. The absence of matches is the contract.

## 2. No LLM in the trust path

The model translates requests and narrates answers. **Deterministic code
decides** who is visible (`app/services/privacy.py`), what is permitted
(`app/services/policy.py`), and how paths are scored
(`app/services/intro_paths.py`). Never move a decision from those modules
into a prompt — a prompt is a suggestion, and suggestions are not access
control.

Corollary for new features: if your change lets model output influence
visibility, permission, or scoring directly, it is wrong even if it works.

## 3. The policy registry is load-bearing

`app/policies.yaml` is a versioned, deny-by-default rulebook evaluated on
**every** tool dispatch.

- A new tool gets a registry entry, or it cannot be called at all.
- **Any rule change bumps `version`** — tests pin it, and they should fail
  when the rulebook changes, because that is what "versioned" means.
- Destructive operations use the server-side two-step: a signed, expiring
  confirm token bound to action + target + user
  (`app/services/confirm_tokens.py`). Never bypass it, never make a
  confirmation UI-only — a confirmation that exists only in the UI is one
  the next caller skips.

## 4. Conventions become contracts

When a convention can be checked mechanically, promote it to a test rather
than documenting it harder. This repo already does this — follow the
pattern, and when you fix a bug that a test could have caught, add the
test in the same commit.

## 5. Privacy is enforced at the query layer

Contact visibility is three-tier (visible / redacted / hidden), applied in
`visible_contacts_query` — **never** in the formatting layer. A redacted
row carries explicit `None`s, not missing keys. If you add a field that
names or narrows down a person, it joins the never-reveal set unless there
is a written reason otherwise.

## 6. Untrusted text is data

Anything a user pastes — and anything fetched from the web — is wrapped in
`<USER_DATA>` delimiters and treated as content, never as instructions.
The eval suite (`evals/`) includes prompt-injection cases; run it when you
touch the prompt, the dispatch loop, or anything that feeds text to the
model. Brand-restricted vocabulary is tested there too — the term list
lives in `evals/cases/banned-words.yaml`, and generated copy should
respect it.

## 7. Working in this repo

- Tests: `pytest` against the `dess_test` database (see
  `tests/conftest.py` for setup). Run the suite before claiming a change
  works; report failures as failures.
- Lint/format: pre-commit runs black, isort, flake8, prettier — let it.
- Types: `mypy --strict` is the bar for new Python.
- The demo dataset is the only dataset. `scripts/seed_dummy_data.py`
  seeds it; `--reset` wipes and re-seeds. There is no path from this
  repository to real data, and pull requests must keep it that way.
