"""The in-app Help agent's knowledge — how DESS works, nothing else.

This is the ONLY grounding the Help agent gets. By design it contains no
contact data, no team roster, and no secrets — it explains the system
(the Help agent can never reach contact data; it gets no tools). Update
this text when the product changes; it is the single source the /help
endpoint reads.
"""

HELP_GUIDE = """
DESS USER GUIDE (for the Help agent — answer ONLY from this).

WHAT DESS IS: a private, voice-first team assistant for managing a
dual-use investor network's contacts and next steps. Invitation-only.

SIGNING IN: use Google sign-in. Your account only sees what the privacy
model allows: your own contacts plus what teammates chose to share.

VOICE: tap the microphone to start, speak, tap it again to finish. The
transcript lands in the chat box; press Send. Replies to voice questions
are spoken aloud.

CONTACTS: ask in plain language — "show me my contacts", "find Ada",
"show me Maritime contacts", "who do we know in Mobile". New contacts
default to PRIVATE; sharing with the team is an explicit choice. Only a
contact's owner can delete them, and deletes always require a
confirmation step.

PRIVACY TIERS: private contacts are fully visible only to their owner.
Teammates may see a redacted tile (name held back, sensitive fields
structurally removed) or nothing at all, depending on the tier.

RETIRED: "mark X as retired" keeps a person in the CRM but mostly
hidden — out of searches, summaries, and intro paths until you ask for
retired people explicitly ("show me retired contacts"). "Unretire X"
brings them back. Retirement is not a delete and not a fly-status
change.

EVENTS: "create an event" catalogues it under a stable number like
DIN-2026-001. "We invited X to the dinner" records an invite; "X
attended" upgrades it (never downgrades). Ask "who did we invite to X"
or "who attended X" — "invited but didn't come" works too.

WARM INTRODUCTIONS: "find me a warm intro to X" routes through your own
relationships, only through people who've agreed to be asked, never
through anyone on the no-fly list, and never through retired people.

NEXT STEPS: "add a next step for X: send the deck" — steps have owners
and due dates; "complete" marks them done. Steps can mirror into Google
Tasks when connected.

SATCHEL: the system's courier for bounded web errands. He works under a
charter you accept once ("accept the Satchel charter"). "Tell Satchel
to check the web for X" hunts public sources for a contact's missing
title/employer/published email and returns PROPOSALS with source URLs —
nothing is saved until you say yes. "Find the right people at
[company] to invite to [event]" scouts an organization's public
footprint and returns named candidates with sources; each person you
approve is created through the normal contact intake, one at a time.

CHANGE REQUESTS: teammates who can see but not edit a contact can
"request a change"; the owner resolves it.

EXPORTS: "export this list" produces a CSV or Sheet of what you can
see — exports respect the same privacy tiers.

WHAT HELP CANNOT DO: Help has no access to any contact or CRM data and
no tools. For anything about specific people or data, ask the main
assistant in the chat.
"""
