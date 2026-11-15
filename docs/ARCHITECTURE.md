# Architecture

Why Loopcaptain is built the way it is. One section per decision; a changed
decision gets a new section that names the one it replaces.

<!-- Every picture on this page is drawn by scripts/readme_assets.py, light and dark: make readme. -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/trust-dark.svg">
  <img alt="Who may do what: the loop writes its files and reads the inbox in its own repository; Loopcaptain reads the files on every request and shows you pages; your answer or stop is appended to the inbox as a signed line; Start runs the one command the loop declared." src="assets/trust-light.svg">
</picture>

The filled tile is where a person decides. Nothing crosses from the board
into a loop except through the inbox file and the one start command the
loop declared for itself.

How one page comes about, file by file:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/request-dark.svg">
  <img alt="How one page comes about: the request passes the host guard, the loop is found among the watched repositories, its files are read and validated, folded into a state, laid out, rendered, and answered as HTML under a content policy." src="assets/request-light.svg">
</picture>

## The parts, file by file

Every tile is a file or a process you can open. A loop writes two files
and reads the third; the board reads all three on every request and
writes only the inbox.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/parts-dark.svg">
  <img alt="The parts of Loopcaptain, file by file: a loop writes its folder itself or through the MCP server or the command line; the board reads the folder through protocol/store.py, folds it into a state and renders pages; your answer or stop is appended to inbox.jsonl, and Start runs the command the loop declared." src="assets/parts-light.svg">
</picture>

The two tiles with the coloured border carry the logic: `fold` turns lines
into a loop's state, and the board's routes are the only way from a browser
to a file. The coloured arrows are the only two ways back into a loop: the
inbox file and the start command the loop declared for itself. The sections
below give the reason for each choice and what was rejected.

## 1. The interface is a folder of files in the loop's repository

**Decision.** A loop shows up by writing `.loops/<loop-id>/loop.json`
and appending to `events.jsonl`; the board appends to `inbox.jsonl`. The
text is `standard/LOOPS.md`, the code `src/loopcaptain/protocol/`.

**Why.** The loops this was built for are scripts in several repositories,
each with its own layout of round folders. What they share is small: a
brief, roles that run in an order, rounds, a file and a verdict per step,
a cost, and a question for the person. Appending one line at the places a
loop already has costs a handful of calls and no dependency, in any
language. Public loop projects have these parts many times over, and no
shared file format with a manifest, verdicts per round, findings and an
item matrix.

**Rejected.**
1. A Python package the loops import and call with typed models: couples
   every loop repository to this one and excludes loops in other
   languages.
2. One rich export file rewritten at the end of every round: a crash
   mid-round shows nothing, two writers race, and the loop must hold the
   whole state to write it.
3. A server the loops post to: a second thing to run, and nothing to show
   when it was not running.
4. Adapters in the board that parse each loop's own files: the board
   would know every loop's layout and break when one changes.
5. Adopting an existing runner (ralph-orchestrator): it shows only loops
   it runs, its gates are tests and lint, and it has no rounds, persistent
   findings or item matrix. Four of its ideas were taken (sections 5, 6).

## 2. Events are appended and folded; nothing is stored twice

**Decision.** `events.jsonl` is append-only. `protocol/state.py` folds
manifest, events and inbox into a `LoopState` on every request; status is
derived, never written. A line the models refuse is reported and skipped.

**Why.** An append cannot corrupt what is already there, a half-written
last line is simply not read yet, and the log doubles as the history. A
pure fold with the clock as an argument makes every status rule a test.

**Rejected.** A database or a cache in the board: a second truth that can
disagree with the files, for loops that write a few hundred lines.

## 3. A script writes the files itself; an agent session writes them through MCP

**Decision.** `src/loopcaptain/mcp_server/server.py` exposes the protocol as
five MCP tools (`protocol`, `loop_register`, `emit`, `inbox_read`,
`loop_status`) that write the same files as the pasted helper and use its
verbs. Scripts do not use it.

**Why.** A loop that an agent session drives has no script to put calls
into; MCP is the portable way in. Everything else is better served by the
script writing its own lines: models skip bookkeeping calls, and tool
definitions cost context. Headless runs load the same MCP configuration as
an interactive session, so an unattended agent can use the tools too.

**Rejected.** MCP as the only interface: every scripted loop would need an
MCP client, and the state would live with a server. One typed tool per
event (twelve tools): more to load into every session, and a second
vocabulary beside the helper's.

## 4. The board is server-rendered, local, and reads fresh

**Decision.** FastAPI with Jinja templates, one stylesheet, one small
script, vendored fonts; bound to 127.0.0.1; every request reads the files
again. No build step, no framework, no CDN.

**Why.** Three pages over a few small files need no client state. Nothing
fetched from elsewhere means nothing about a loop leaves the laptop, and a
strict content policy (`default-src 'self'`) is possible because no page
carries inline script or style.

**Rejected.** A single-page app: a build step and a second copy of the
state. A static export: no reply box.

## 5. Steering is an inbox file and one declared command

**Decision.** The answer box and "Stop after this round" append to
`inbox.jsonl`; the loop reads it at the start of a round and marks entries
read with `inbox_read`. "Start" runs `commands.start` from the loop's own
`loop.json`, split into arguments, without a shell, in the loop's
repository (`board/steer.py`). Every changing request carries the server
process's token, and every request must name the server as host. A
`question` may say that it blocks and for how long.

**Why.** The person steers without knowing where a loop keeps its thread
file. The loop stays in charge of what it does with a reply. A browser
that can run only what the loop's repository declared cannot be turned
into a shell by another web page.

**Rejected.** Writing the reply into the loop's own files: the board
would need each loop's format. Running a command typed in the browser.
Killing as the normal stop: a round's work would be lost; the board
offers it only for a process it started itself.

## 6. Steps are plain data: no vendor, no runtime

**Decision.** A step has an id, a kind, and free-text `backend` and
`model`; order comes from the list, `after` where a step does not follow
the one before. Caps (`round_cap`, `runtime_cap_minutes`, `cost_cap_usd`)
are the loop's own; the board shows them and marks an idle loop that
reached one as capped. `standard/templates/` holds three manifests to
copy.

**Why.** The board must work with any runner and any agent. `after` draws
every graph the known loops have (a sequence, a fan of reviewers, a gate
that joins them) with one optional field.

**Rejected.** Steps that declare the events they wait for and emit: more
general, and a second vocabulary to learn for a picture the board can
already draw. The board enforcing caps: it does not run the loop.

## 7. Reviews are fresh each round

**Decision.** What is open is what the last reviewed round's steps found
and nobody closed (`LoopState.open_findings`). A finding has an id within
its step and round, a text and a severity, `material` or `minor`.

**Why.** It is how the known loops review: fresh agents each round, a
count of material gaps per reviewer. It needs no identity of a finding
across rounds.

**Rejected for now.** Stable fingerprints that follow a finding across
rounds and four severities: `.agent/FINDINGS.md` (F5, F7).

## 8. One standard folder, neutral and copyable

**Decision.** `standard/` holds what another repository needs: the text,
the helper, templates, the JSON Schema, and an `AGENTS.md` that tells an
agent how to make a loop meet it. The spec has that one home; the package
carries a copy when built. Nothing in the repository names a company or a
client (`tests/test_neutral.py`).

**Why.** Connecting a loop is one sentence and one link, and the project
is meant to be opened to others.

**Rejected.** The spec inside the package folder: correct for Python,
invisible to someone browsing the repository.

## 9. The look: calm, one action colour, status by shape

**Decision.** `board/static/style.css` starts from tokens: a warm light
canvas and true black in dark mode, soft surfaces, one action colour
(iris) for links, the answer button and "waiting for you", Inter Tight
over Inter, a 12/14/16/20/26/36 scale, 4/8-point spacing, 44 px controls.
Status has its own colours and its own shapes. Open findings are an ink
ramp. The logo is `static/mark.svg`.

**Why.** The page exists to show the one thing that needs the person;
everything else has to be quiet for that to work, and it has to read
without colour.

**Rejected.** A red accent for both "needs you" and "finding": the two
would compete on every page.

## 10. What this is not, and what sits beside it

**Decision.** No agent runtime, no scheduler, no transcript store, no
cloud, no login, no GitHub API. Loops that run on a CI service appear
once their checkout holds a `.loops/` folder.

**Why.** Session boards from vendors already cover live sessions; a
dashboard of CI agent runs is a different tool that reads a hosting
service. The part nobody else has is the file format across runners.

## 11. The on-disk names are plain, the outcome of a round is two fields

**Decision.** A loop's folder is `.loops/<loop-id>/` and the text is
`standard/LOOPS.md`, "the loops protocol"; neither carries the name of this
application. A sub-folder is a loop only if its `loop.json` has the
`protocol` field. `round_finished` carries `verdict` (continue, done, wait,
stopped, failed) and an optional `stop_reason` (goal_met, round_cap,
cost_cap, runtime_cap, person, no_progress, error); `finding_closed`
carries an optional `resolution` (fixed, accepted, wontfix, false_positive,
duplicate). The text ends with what a loop and a board MUST, SHOULD and MAY
do, and how versions grow.

**Why.** The application's name is not settled and a protocol should
outlive the tool that reads it, like `.github/`. Other tools already keep
files under `.loops/`, so the `protocol` field is what marks a loop.
`stopped` alone could not tell a person's stop from a cap, and nothing
said "waiting for the person"; closing a finding could not tell fixed from
waved off. Both are one optional field with a closed list of values.

**Rejected.** A folder named after the application: it would have to
change with the name. Free text for the reason: a board cannot show it as
a status. The wider vocabulary of other loop tooling (control roles,
criteria ids, gates as data, run ids): each is a word every loop author
must learn, and unknown fields are already allowed.

## 12. The board signs the inbox; a loop decides what to do with an unsigned line

**Decision.** Every line the board appends to `inbox.jsonl` carries `sig`,
an HMAC-SHA256 over the line without `sig` in a canonical JSON form. The
key is `~/.config/loopcaptain/inbox.key` (or the file `LOOPCAPTAIN_INBOX_KEY`
names), created on first use, readable by the user only, outside every
watched repository (`protocol/signing.py`). The helper and the MCP tool
`inbox_read` add `signed` to each entry: true, false, or null where the
machine has no key. `sig` is an optional field of protocol 1. Starting a
loop passes only `PATH`, `HOME`, `LANG` and `TERM`, so the key's path is
not handed over in the environment either.

**Why.** The inbox is a plain file in the loop's repository. A loop whose
agents write files could not tell the board's `reply` from an agent's, and
a forged `stop` would end the run (F14 g). A signature keeps the inbox
where every loop already reads it, and the helper stays standard library.

**Rejected.** An inbox outside the repository: every loop would need to
learn a second path, and a loop on another machine could not read it. A
public-key signature: the standard library has no Ed25519, and the helper
must stay a paste. Refusing unsigned lines in the board's own fold: the
board shows what is in the file; acting on it is the loop's decision.
What it does not stop: a process with the user's full file access can
read the key. It guards against agents confined to their repository.

## 13. Worktrees of one repository are one repository

**Decision.** `board/discover.py` groups the folders it finds by the `.git`
folder they share, read from the `.git` file of a worktree without running
git. A group shows once, from the worktree whose `.loops/` was written
last; the loop page names it and lists the others in a tooltip.

**Why.** A loop that runs in its own worktree, as the "one worktree per
writer" rule asks, sits beside the main checkout under the same root. The
board listed each of its loops twice, from copies that disagreed, and a
person could steer the stale one.

**Rejected.** `git rev-parse --git-common-dir` per folder: a process per
repository on every request, where one small file read answers the same.
Merging the copies' events: two folders are two truths, and the last
written one is the one a running loop writes.

## 14. Protocol 1 grows by what real loops and published practice need

**Decision.** Optional fields and three events, all in protocol 1:
`at` on any event (when it happened, beside `ts`, when it was written);
`cost` on `round_finished` (the round's sum) with cache tokens, turns and
`estimated`; `metrics` on steps and rounds; `attempt`, `error` and
`session` on `step_finished`; `outcome`, `next_at` and the stop reason
`impossible` on `round_finished`; `id` and `options` on `question`, with
`question` and `choice` on a reply; `workspace` and `state` in
`loop.json`; the events `question_closed`, `loop_stopped` and
`heartbeat`. The fold (`protocol/state.py`) measures time on `at`, shows
a loop that said when it is back as `sleeping`, and turns an error of
kind `needs_person` into something that waits for the person.

**Why.** The first real loop could not report a round's cost as a sum,
end a question it settled itself, stop between rounds without rewriting
the last verdict, or keep real times when it reported after the fact
(F14). Published loop practice adds a measure per round
(autoresearch, harness design), sleeping schedules, questions with
choices, errors only a person can fix, cache-heavy token use without a
price, and discarded experiments. Every addition is optional, so a loop
written against the earlier text still validates.

**Rejected.** `round_finished` without `round` for a stop between rounds:
it would make the most important field of the most important event
optional. A `supersedes` field on `question`: a loop that settles a
question elsewhere has no new question to ask. Protocol 2: nothing here
breaks a loop of today. Finding fingerprints (F5): no real loop has asked
for them yet.

## 15. No OpenTelemetry code; a mapping instead, and the files are the interface

**Decision.** Loopcaptain sends and takes no telemetry. `docs/opentelemetry.md`
maps the protocol onto the OpenTelemetry GenAI conventions, marked as
following a draft. A loop that runs elsewhere syncs its `.loops/` folder
to where the board reads; the board stays local. An exporter that tails
`events.jsonl` and sends OTLP is a finding (F15), to build when someone
wants loops beside agent traces in one place.

**Why.** The GenAI agent conventions are in development status and moved
to their own repository, `open-telemetry/semantic-conventions-genai`,
without a stable release (that repository, read 2026-11-14):
code against them breaks, a table is cheap to change. The agents already
emit telemetry for each model call, tokens and cost included, at the
source. What Loopcaptain adds is the layer above, rounds, steps, findings,
verdicts and questions, which no convention models. Taking spans in would
need a port and a store, a second truth that section 2 rejects. Sending
spans out is the first thing that would move data off the machine, so it
belongs in a separate, optional process.

**Rejected.** An OTLP receiver in the board: a server and a store. An
exporter inside the board: data leaves the machine from the process that
promises it does not. A connector per platform: any backend that takes
OTLP is served by one exporter.

## 16. The board's own status trusts only signed lines, and a line names its loop

Replaces part of section 12, which rejected refusing unsigned lines in the
board's fold.

**Decision.** `fold` takes the ids of inbox entries whose signature fails
(`signing.untrusted_ids`). They are listed on the "What you sent" tab, but
answer no question, clear no "needs you" and request no stop. Each line
the board writes carries `loop`, inside the signed body, and a line for
another loop does not verify. Where the machine has no key yet, nothing
can be told apart and every line counts, as before. The key is written
whole and linked into place, and a key shorter than 32 bytes is not used.

**Why.** An independent review found that a reply an agent wrote into its
own repository's inbox turned a waiting loop to idle: the person was no
longer asked, though the line showed as "not from the board". A signed
stop copied from one loop's inbox into another's verified there too.

**Rejected.** Hiding unsigned lines: the person should see that someone
wrote into the inbox. Binding the line to the repository's path as well:
a repository moved or cloned elsewhere would lose every signature, and a
loop id is unique within the repositories one person watches.

## 17. A started loop gets the key's path; a stop in a round that met its goal is `done`

Replaces the last sentence of section 12's decision.

**Decision.** Start passes `LOOPCAPTAIN_INBOX_KEY` beside `PATH`, `HOME`,
`LANG` and `TERM` (`board/steer.py`). A stop read during a round ends it
with its real verdict: `done` if the goal was met, else `stopped`; a stop
read between rounds is `loop_stopped`. `doctor` accepts all three. The
helper writes `ts` to the millisecond.

**Why.** A first loop built from nothing by a fresh agent, given only the
first prompt, stumbled here: with a key at a custom path the started
loop could not check a signature and acted on any line; the spec's own
example loop broke out on a stop without saying so and failed `doctor`;
nothing said which verdict wins when a stop and the goal meet; a loop of
plain functions finishes a round within a second, so whole-second times
made every honest round look written after the fact.

**Rejected.** Keeping the key's path from a started loop: the path is not
the key, and the loop needs it to tell the person from its own agents.
`stopped` over `done`: the board would report a goal not met that was.

## 18. Apache License 2.0 for the code and the standard

**Decision.** Everything in the repository is under the Apache License 2.0:
`LICENSE` holds the text, `NOTICE` the copyright line and the fonts'
licence, `pyproject.toml` names all three as `license-files` so a built
package carries them, and `CITATION.cff` says the same. A contribution is
taken under the same licence (`CONTRIBUTING.md`); there is no contributor
agreement.

**Why.** A standard is adopted only if a company's lawyers can say yes
without a meeting. Apache 2.0 is permissive, widely pre-approved, and
carries an explicit patent grant from every contributor, which a protocol
others implement needs more than a library does.

**Rejected.** MIT: shorter, but silent on patents. A copyleft licence
(GPL, AGPL): a loop would hesitate to paste the helper. A source-available
licence: not open source, and no standard grows under one.

## 19. Releases are cut from the commits, not by hand

**Decision.** On every push to `main`, `.github/workflows/release.yml` runs
`scripts/release.py`. It reads the commits since the last tag: a `feat`
raises the minor version, a `fix` or `perf` the patch, a breaking change
the major (the minor before 1.0); anything else makes no release. The
workflow then builds the wheel with that version, smoke-tests it, and
creates the tag and the GitHub release with the commit subjects as notes
and the wheel attached. Nothing is committed back: `pyproject.toml` says
`0.0.0`.

**Why.** A version bumped and tagged by hand is a step that is forgotten
or done differently each time. The commits already say what changed and
how much, once their types are held to one meaning (AGENTS.md, "Commits
and pull requests"). Creating a tag needs only the workflow's permission
to write contents, which is set in the workflow file itself.

**Rejected.** A release pull request kept open by a bot (release-please):
it needs the repository to let Actions create pull requests, and a second
merge per release. A tag pushed by hand after a version bump: two manual
steps. A version read from the git tag at build time: an install from a
source archive or a shallow clone has no tag to read. Committing the
version back to `main`: a push to a protected branch by a workflow.

## 20. A step reports the model it really ran on

**Decision.** `step_finished` takes an optional `model`
(`protocol/models.py`, `standard/LOOPS.md` section 2); the round page shows
it beside the session. A round's mode (research or write) gets no field:
the loop says it in the first words of `plan`.

**Why.** The real loops retry a step on a second model when the first
refuses to start, so the `model` a step names in `loop.json` can be wrong
for a given run, and a person reading a weak review needs to know which
model wrote it. The mode only decides which steps run, and the board
already shows the steps that ran.

**Rejected.** Rewriting `loop.json` with the fallback model: it is the
loop's declaration, and the next run would start on the wrong one. A
`mode` field on `round_started`: vocabulary every loop author learns for
one loop's sake.

## 21. A run that starts its count over is a loop of its own

**Decision.** `standard/LOOPS.md` says a run that counts its rounds from 1
again gets its own loop id; `loopcaptain validate` warns when a round
starts below one already started (`restarted_count` in
`protocol/validate.py`). The protocol gets no `run` field.

**Why.** A real loop runs a study several times, each run on its own
branch with its own corpus and round count. In one folder, round 3 of the
second run would replace round 3 of the first. A loop id per run keeps
them apart with what the protocol already has, and the overview lists the
runs side by side.

**Rejected.** A `run` field on every event: vocabulary every loop author
learns, and a fold that has to key rounds by two numbers. Numbering rounds
on across runs: the loop's own files count from 1, so the board and the
loop would disagree.
