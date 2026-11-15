# Loopcaptain: agent instructions

The single source of truth. `CLAUDE.md` and `GEMINI.md` only point here. §A
is for using the board and connecting a loop, §B for changing this
repository.

One board for every agent loop on a laptop. A loop, in its own repository,
writes three small files into `.loops/<loop-id>/`; the board reads them,
shows where the loop stands, and writes the person's answers back. A loop
never imports this repository.

## Where things are

| You want to | Go to |
|---|---|
| Connect a loop in another repository | [standard/AGENTS.md](standard/AGENTS.md) |
| Read the standard | [standard/LOOPS.md](standard/LOOPS.md) |
| Change what a loop may say (a field, an event) | [src/loopcaptain/protocol/AGENTS.md](src/loopcaptain/protocol/AGENTS.md) |
| Change a page, the look, the graph, steering | [src/loopcaptain/board/AGENTS.md](src/loopcaptain/board/AGENTS.md) |
| Change an MCP tool | [src/loopcaptain/mcp_server/AGENTS.md](src/loopcaptain/mcp_server/AGENTS.md) |
| Know why it is built this way | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| See what is open | the ledgers in [.agent/](.agent) |

---

## §A. Using it

The runbook for an agent asked to set the board up for someone ("help me
see and steer the agent loops on this machine"). Commands are written for
a checkout; with the package installed, drop `uv run`.

### 1. Ask first

1. Which folders hold the repositories to watch (`~/projects`, a work
   folder)? A folder of repositories nobody has read does not go on the
   board: its loops' Start buttons run what those repositories declare.
2. Which of their loops should the person see first, and which may never
   be started from the board?
3. Should the board run only while asked, or stay up?

### 2. Cheapest run first

```bash
make setup                   # once: dependencies, git hooks
make demo                    # the example loop in demo/; free, no model, no network
make serve                   # the board on http://127.0.0.1:8484
```

Open the example loop, press Start, answer its question with a button,
watch it converge and end `done`. Then the person knows what a connected
loop looks like.

### 3. Find the loops

1. A repository that already reports has a `.loops/` folder:
   `find <folder> -maxdepth 3 -name .loops -type d`.
2. One that runs a loop without reporting has a loop script, a rounds or
   reviews folder, or a loop described in its own `AGENTS.md`. List them
   for the person; change nothing in them before they agree.
3. Check each reporting repository: `uv run loopcaptain validate <repo>`
   (problems and warnings) and, with its loop running, `uv run loopcaptain
   doctor <repo> <loop-id>` (does it take a stop?).

### 4. Watch them

```bash
uv run loopcaptain watch <folder> --root     # every sub-folder with .loops/
uv run loopcaptain watch <repository>        # one repository
uv run loopcaptain unwatch <folder>
```

This edits `~/.config/loopcaptain/config.yaml`, or the file
`LOOPCAPTAIN_CONFIG` names; `loopcaptain.local.yaml` beside the Makefile
wins in a checkout and is never committed. Worktrees of one repository
show once.

### 5. Connect what does not report

Work in the loop's repository, not here, and follow
[standard/AGENTS.md](standard/AGENTS.md); propose the smallest change and
wait for a yes. Do not add this repository as a dependency of a loop. A
loop an agent session drives adds the MCP server, `loopcaptain mcp` over
stdio: `uv run loopcaptain mcp-config <agent>` prints the line for it,
[docs/agents.md](docs/agents.md) lists every agent.

### What the board does and does not do

1. **Steering.** An answer, a note or "Stop" append a signed line to the
   loop's `inbox.jsonl`. "Start" runs `commands.start` from the loop's own
   `loop.json` in its repository, without a shell and with only `PATH`,
   `HOME`, `LANG`, `TERM` and `LOOPCAPTAIN_INBOX_KEY` from the board's environment; the first start
   of a command asks for a tick. The board runs nothing else, and nothing
   typed in a browser.
2. **What it reads.** Only files inside a watched repository, never `.git`,
   `.env*`, key or credential files, and the content of text files only.
   It copies nothing and sends nothing anywhere. See
   [SECURITY.md](SECURITY.md).

---

## §B. Changing this repository

### How a change moves

1. **Branch.** Off `main`, one branch and one worktree per writer. A
   running board (`make serve`) reads templates and static files from the
   checkout it was started in; restart it after a Python change.
2. **One milestone.** One logical change, a test that fails without it,
   `make check`, one commit.
3. **Show it.** Run the change for real once: `make demo`, `make serve`,
   look at the page or start the live demo loop. Until then it is listed in
   `.agent/DEFERRED_VERIFICATION.md`.
4. **Route what is not the task.** Anything noticed on the way goes to a
   ledger in `.agent/`, not into this change.
5. **Integrate.** Up to date with `main`, `make check`, one independent
   review pass, then at most one recheck. Merge by fast-forward only. Push
   only when the person says so; never force-push.
6. **Close.** Ledgers updated, worktree clean, branch merged or deleted.

### Releasing

1. Nobody bumps a version, pushes a tag or opens a pull request for a
   release. On every push to `main` the release workflow
   (`.github/workflows/release.yml`) runs `scripts/release.py`, which reads
   the commits since the last tag.
2. The version follows the commit types (the table under "Commits and
   pull requests"): `fix` and `perf` raise the patch number, `feat` the
   minor one. Before 1.0 a breaking change raises the minor number, after
   it the major one. A push with only `docs`, `test`, `chore`, `ci` or
   `refactor` commits makes no release.
3. A release is a tag `vX.Y.Z` and a GitHub release whose notes are the
   subjects of those commits, with the wheel attached: built with the
   tag's version, installed in a clean environment and smoke-tested first.
   It goes to PyPI once the repository variable `PUBLISH_PYPI` is `true`.
4. Nothing is committed back. `pyproject.toml` says `0.0.0`; a checkout
   and an install from `main` report that, a released wheel its tag.
5. A commit subject is a line of the release notes, so write it for a
   user. `CHANGELOG.md` holds the first version and points to the
   releases.
6. The package version is not the protocol number: a release may add
   optional fields and events, never break a loop written today.
7. Not on PyPI yet: the documentation installs from the repository.

### Where each fact lives

| Fact | Owner |
|---|---|
| What a loop writes and the board reads | `standard/LOOPS.md`, and the models in `src/loopcaptain/protocol/models.py` |
| Rules, commands, how a change moves | this file |
| Why it is built the way it is | `docs/ARCHITECTURE.md` |
| Setup, first run, everyday use | `README.md` |
| What changed for users | the release notes on GitHub, written from the subjects of `feat`, `fix` and `perf` commits |
| Work a person has chosen to do | `docs/BACKLOG.md`, created when the first finding is picked |
| Open observations and proposals | the ledgers in `.agent/` |

### Rules

1. **The standard changes in three places at once, or not at all:**
   `standard/LOOPS.md` (the text), `src/loopcaptain/protocol/models.py`
   (the code), `standard/schema/` (`make schema`). Tests hold the three
   together, and hold `standard/loops.py` and the demo loop to the
   helper the text prints.
2. **A loop must stay able to connect without this repository.** Nothing
   in `standard/` may require installing anything. The helper is standard
   library only.
3. **Version 1 only grows.** New optional fields and new events are fine;
   a loop written against today's text must keep validating. Anything else
   is protocol 2 and a decision for `docs/ARCHITECTURE.md`.
4. **The board is read-only towards a loop, except the inbox.** It never
   writes `loop.json` or `events.jsonl`, never edits a loop's own files.
5. **The board runs one thing:** `commands.start` of a loop's `loop.json`,
   split into arguments, no shell. No other route to a process.
6. **No page loads anything from another origin,** and no template carries
   inline script or style: the content policy in `board/app.py` forbids it
   and a test checks it. The font is vendored.
7. **Every form carries the server's token and every request names this
   server as host.** A new route that changes anything takes the token.
8. **Neutral and invented.** An agent product may be named as an example
   ("Claude Code's `/loop`"); nothing may need one to run or to be
   understood. No company, client or real loop is named anywhere, the
   repository's own address excepted (`[project.urls]` in
   `pyproject.toml`): not in code, pages, the standard, fixtures, the demo or the
   screenshots. The refused names live only in `.forbidden-words.local`
   (one per line, never committed); the pre-commit hook and
   `tests/test_neutral.py` both read it, and the test is skipped without it.
9. **Python:** 3.12, `uv`, `ruff` at 110, `mypy` strict, `pytest`. No
   module-level helper with a `_` prefix, no `**kwargs` catch-all,
   `logging` instead of `print` outside the command line.
10. **Commits and pull requests** follow the section below: Conventional
    Commits, and text about the change, never about the conversation that
    led to it.

### Commits and pull requests

A commit message and a pull request description are read by a stranger,
years later, who has the repository and nothing else.

1. **Conventional Commits.** The subject is `type(scope): subject`:
   imperative, under 72 characters, no full stop. The body is bullets that
   say why. The type decides what a release does with the commit:

   | Type | Use it for | Release |
   |---|---|---|
   | `fix`, `perf` | a fault a user could meet, or the same thing faster | patch |
   | `feat` | something a user can newly do or see | minor |
   | `feat!`, `fix!`, or a `BREAKING CHANGE:` footer | a loop or a command of today stops working | major |
   | `docs`, `test`, `refactor`, `ci`, `build`, `chore`, `style`, `revert` | everything else | none |

2. **A pull request title is a commit subject** of the same form. It names
   the change that matters most to a user.
3. **Say what changes, why, and how it was checked.** "Why" is the problem
   as the repository shows it: what a reader saw, what failed, what was
   missing. Every sentence must make sense without the conversation.
4. **Never the conversation.** Not who asked for the change, what anyone
   said, wanted, liked or disliked, what was discussed or agreed, or what
   a session did on the way. Not "as requested", "per the review", "the
   user wants", "we discussed". Write "the heading read as a fault", not
   "the maintainer does not want readers to think it is broken".
5. **Length follows the change.** Everything a reader needs to judge it,
   and nothing that is background: no history of attempts, no options
   that were not taken unless a later reader would retry them.
6. **No AI attribution, no agent, model, tool or session named, no
   absolute paths.**

The commit-msg hooks check the subject's form, attribution, and the
commonest phrases of rule 4 (`.pre-commit-config.yaml`). They catch the
phrase, not the habit: the rule is the text above.

### Checks

`make check` is what CI runs: `ruff format --check`, `ruff check`, `mypy`,
`pytest` with coverage of at least 85 percent. The tests need no network
and no model.

### Things that will bite you

1. **The spec has one home, `standard/LOOPS.md`.** A built package
   carries a copy (pyproject.toml, `force-include`); in a checkout
   `spec_text()` reads the file in `standard/`. Do not add a second copy
   under `src/`.
2. **`make schema` after any model change,** or
   `test_the_published_schema_is_current` fails.
3. **The helper appears twice by design:** in the spec's text and as
   `standard/loops.py`, which `loopcaptain demo` copies beside the example
   loop (`src/loopcaptain/demo/loop.py`). Change the spec, then copy; tests
   compare them byte for byte.
4. **A running board does not reload Python.** Restart `make serve` after a
   change under `src/`.
5. **`demo/` and `.state/` are local.** `make demo` rewrites `.loops/`,
   `work/` and `out/` in `demo/` where it finds the example's `loop.py`.
   Never point `--target` at a real repository. The example loop is the
   only loop in this repository; no real loop's folder is ever committed.
6. **Status is derived, never stored.** "running" means a round is open
   and a line arrived in the last 45 minutes (`STALE_AFTER`), or the board
   itself started the process and it is alive. A loop that dies mid-round
   shows as stalled, not failed.
7. **The pid the board remembers survives a restart of the board,** with
   the machine's boot time beside it: a record from before a reboot never
   reads as alive. The boot time comes from a clock, not from `ps`, since
   the board runs nothing but `commands.start`.
8. **The page reloads itself every few seconds while files change,** but
   not while a textarea holds text. A template that adds a form field must
   keep that rule in `static/board.js`.

### Definition of done

1. A test that fails without the change, and `make check` is green.
2. The change was looked at for real: `make demo`, `make serve`, the page
   or the live demo loop. Otherwise a row in
   `.agent/DEFERRED_VERIFICATION.md`.
3. Text, models and schema of the standard agree (rule 1).
4. The subject of a `feat` or `fix` commit says what changed for a user,
   since it becomes a line of the release notes; a decision has its section
   in `docs/ARCHITECTURE.md`.
5. Nothing names a company, a client or a real loop (rule 8).
6. One logical change per commit; nothing pushed without the person's yes.
