<!-- The title is a commit subject: type(scope): subject. Write about the change, never about the
     conversation that led to it: no "as requested", no "the user wants". AGENTS.md has the rules. -->

## What changes for a user

<!-- One or two sentences. The subjects of the feat and fix commits become the changelog. -->

## Why

<!-- The problem, with evidence: an issue, a finding, a run. -->

## Done when

- [ ] A test fails without this change, and `make check` is green.
- [ ] Looked at for real (`make demo`, `make serve`), or listed in `.agent/DEFERRED_VERIFICATION.md`.
- [ ] Text, models and schema of the standard agree (`make schema`), if the protocol changed.
- [ ] `feat` and `fix` subjects read as changelog lines; a decision has its section in `docs/ARCHITECTURE.md`.
- [ ] Nothing names a company, a client or a real loop.
- [ ] The title and this text describe the change, not the conversation that led to it.
