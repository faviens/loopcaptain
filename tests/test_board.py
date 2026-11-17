"""The pages, the forms and the guards of the board, over a temporary repository."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from loopcaptain.board import steer, trend
from loopcaptain.board.app import STATUS_ORDER, create_app
from loopcaptain.board.discover import Config, Repo, find_repos, load_config, parse_config
from loopcaptain.board.graph import columns, layout
from loopcaptain.board.steer import Runner
from loopcaptain.cli import main as cli_main
from loopcaptain.protocol import signing, store
from loopcaptain.protocol.models import Manifest
from loopcaptain.protocol.state import STATUS_TEXT, FindingState, LoopState, RoundState, Status, StepRun
from loopcaptain.protocol.store import StoreError
from tests.conftest import STEPS

HOST = "board.test"


@pytest.fixture
def client(scan: Path, tmp_path: Path) -> TestClient:
    app = create_app(
        config=lambda: Config(repos=(scan,)),
        runner=Runner(tmp_path / "state"),
        allowed_hosts=frozenset({HOST}),
    )
    return let_in(TestClient(app, base_url=f"http://{HOST}", follow_redirects=False))


def let_in(client: TestClient) -> TestClient:
    """The client as a browser that opened the address `serve` printed."""
    session = client.app.state.session  # type: ignore[attr-defined]
    client.cookies.set(session.cookie_name, session.issue() or "")
    return client


def token_of(client: TestClient) -> str:
    return str(client.app.state.token)  # type: ignore[attr-defined]


def test_overview_lists_the_loop_with_its_status_and_cost(client: TestClient) -> None:
    page = client.get("/")

    assert page.status_code == 200
    assert "Market scan" in page.text and "$0.75" in page.text and 'class="pill running"' in page.text


def test_overview_groups_the_loops_under_the_project_they_live_in(client: TestClient, scan: Path) -> None:
    page = client.get("/").text

    project = page[
        page.index('<tr class="project">') : page.index("</tr>", page.index('<tr class="project">'))
    ]
    assert "Project" in project and "some-repo" in project and "1 loop" in project
    assert str(scan.parent.name) in project  # where the repository is, not only its name
    assert '<span class="id">scan</span>' in page


def test_overview_has_a_tab_for_what_waits_marked_only_when_something_does(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    quiet = client.get("/").text
    assert 'href="http://board.test/?tab=waiting"' in quiet and 'class="n hot"' not in quiet

    helper.emit("scan", "question", {"round": 2, "text": "Per seat or per site?"}, scan)
    loops, waiting = client.get("/").text, client.get("/?tab=waiting").text

    assert 'class="n hot"' in loops and 'class="waits"' in loops
    assert "Per seat or per site?" not in loops and "<table" in loops
    assert "Per seat or per site?" in waiting and "<table" not in waiting
    assert client.get("/?tab=nonsense").text.count("<table") == 1


def test_a_question_on_the_overview_names_its_project_and_its_loop(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Per seat or per site?"}, scan)

    page = client.get("/?tab=waiting").text

    card = page[
        page.index('<section class="ask"') : page.index("</section>", page.index('<section class="ask"'))
    ]
    assert "<dt>Project</dt><dd>some-repo</dd>" in card
    assert "<dt>Loop</dt>" in card and "Market scan" in card and "round 2" in card


def test_the_overview_pulse_reads_no_loop_and_matches_the_page(
    client: TestClient, scan: Path, helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = client.get("/").text
    drawn = re.search(r'data-pulse="([^"]*)"', page)
    assert drawn is not None

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the pulse parsed a loop")

    monkeypatch.setattr("loopcaptain.board.app.load_loop", refuse)
    assert client.get("/pulse").json()["pulse"] == drawn.group(1)
    helper.emit("scan", "check", {"item": "x", "kind": "y", "result": "pass"}, scan)
    assert client.get("/pulse").json()["pulse"] != drawn.group(1)


def test_the_waiting_tab_says_so_when_nothing_waits(client: TestClient) -> None:
    assert "Nothing waits for you" in client.get("/?tab=waiting").text


def test_the_overview_tab_shows_the_graph_and_the_brief_but_no_round_table(client: TestClient) -> None:
    page = client.get("/loop/some-repo/scan")

    assert page.status_code == 200
    assert page.text.count('<g class="node') == 7
    assert 'aria-current="page">Overview' in page.text
    assert "<h2>Round" not in page.text and 'class="grid"' not in page.text


def test_a_link_to_a_round_opens_the_rounds_tab_on_that_round(client: TestClient) -> None:
    page = client.get("/loop/some-repo/scan?round=1")

    assert 'aria-current="page">Rounds' in page.text and 'class="grid"' in page.text
    assert "<h2>Round 1</h2>" in page.text and "abc1234" in page.text
    assert "No source for 40 percent." in page.text and "closed: Fixed." in page.text
    assert '<g class="node' not in page.text


def test_the_findings_tab_lists_what_is_open_now(client: TestClient) -> None:
    page = client.get("/loop/some-repo/scan?tab=findings")

    assert 'aria-current="page">Open findings<span class="n">1</span>' in page.text
    assert "No source for 40 percent." in page.text and "Typo." not in page.text


def test_the_items_tab_shows_checks_and_an_unknown_tab_is_the_overview(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    assert "?tab=items" not in client.get("/loop/some-repo/scan").text
    helper.emit("scan", "check", {"item": "Tool A", "kind": "own trial", "result": "pass"}, scan)

    items = client.get("/loop/some-repo/scan?tab=items")
    unknown = client.get("/loop/some-repo/scan?tab=nonsense")

    assert "Tool A" in items.text and 'class="res pass"' in items.text and 'class="void"' not in items.text
    assert 'aria-current="page">Overview' in unknown.text


def test_a_question_shows_on_both_pages_and_the_answer_lands_in_the_inbox(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "question", {"round": 2, "text": "Per seat or per site?"}, scan)
    assert "Per seat or per site?" in client.get("/?tab=waiting").text
    assert "Per seat or per site?" in client.get("/loop/some-repo/scan").text

    sent = client.post("/loop/some-repo/scan/reply", data={"token": token_of(client), "text": " Per seat. "})

    assert sent.status_code == 303 and "note=Sent" in sent.headers["location"]
    entries, _ = store.read_inbox(scan, "scan")
    assert [(entry.kind, entry.text, entry.round) for entry in entries] == [("reply", "Per seat.", 2)]
    assert "Per seat or per site?" not in client.get("/?tab=waiting").text


def test_stop_is_written_once(client: TestClient, scan: Path) -> None:
    for _ in range(2):
        client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})

    entries, _ = store.read_inbox(scan, "scan")
    assert [entry.kind for entry in entries] == ["stop"]
    assert "Stop is waiting" in client.get("/loop/some-repo/scan").text


@pytest.mark.parametrize("action", ["reply", "stop", "start", "kill"])
def test_a_form_without_this_servers_token_changes_nothing(
    client: TestClient, scan: Path, action: str
) -> None:
    wrong = client.post(f"/loop/some-repo/scan/{action}", data={"token": "guess", "text": "hello"})
    missing = client.post(f"/loop/some-repo/scan/{action}", data={"text": "hello"})

    assert (wrong.status_code, missing.status_code) == (303, 422)
    assert wrong.headers["location"].startswith("/loop/some-repo/scan?error=Nothing%20was%20sent")
    assert store.read_inbox(scan, "scan") == ([], [])
    assert not (scan / "started").exists()


def test_a_request_for_another_host_is_refused(client: TestClient) -> None:
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400


def test_an_empty_reply_is_not_sent(client: TestClient, scan: Path) -> None:
    sent = client.post("/loop/some-repo/scan/reply", data={"token": token_of(client), "text": "   "})

    assert "error=Nothing" in sent.headers["location"]
    assert store.read_inbox(scan, "scan") == ([], [])


def test_a_message_shows_only_when_this_server_wrote_it(client: TestClient, scan: Path) -> None:
    crafted = client.get("/loop/some-repo/scan?note=Stop%20sent.&error=Your%20key%20leaked&seal=%C3%BC")
    sent = client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})
    followed = client.get(sent.headers["location"])
    tampered = client.get(sent.headers["location"].replace("Stop%20sent", "Nothing%20sent"))

    assert "Stop sent." not in crafted.text and "Your key leaked" not in crafted.text
    assert "Stop sent. The loop ends after its current round." in followed.text
    assert 'class="flash' not in tampered.text


def test_files_render_inside_the_repository_only(client: TestClient, scan: Path) -> None:
    (scan / "notes.md").write_text("# Plan\n\n<script>alert(1)</script>\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    (scan.parent / "outside.md").write_text("secret")

    inside = client.get("/loop/some-repo/scan/file", params={"path": "notes.md"})

    assert inside.status_code == 200 and "<h1>Plan</h1>" in inside.text and "<table>" in inside.text
    assert "<script>alert" not in inside.text
    for path in ("../outside.md", "/etc/passwd", "missing.md", ""):
        assert client.get("/loop/some-repo/scan/file", params={"path": path}).status_code == 404


def test_pages_send_a_policy_that_forbids_inline_script_and_carry_none(client: TestClient) -> None:
    page = client.get("/loop/some-repo/scan")

    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert not re.search(r"<script(?![^>]*\bsrc=)", page.text)
    assert " style=" not in page.text and " onclick=" not in page.text


def test_unknown_loops_and_repositories_are_404(client: TestClient) -> None:
    assert client.get("/loop/some-repo/ghost").status_code == 404
    assert client.get("/loop/other-repo/scan").status_code == 404


def test_the_pulse_changes_when_the_loop_writes(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    before = client.get("/loop/some-repo/scan/pulse").json()["pulse"]
    helper.emit("scan", "step_finished", {"round": 2, "step": "plan"}, scan)

    assert client.get("/loop/some-repo/scan/pulse").json()["pulse"] != before


def test_connect_page_serves_the_spec_for_copying(client: TestClient) -> None:
    assert "Loops protocol, version 1" in client.get("/connect").text
    assert client.get("/connect/LOOPS.md").text.startswith("# Loops protocol")


def test_a_loop_with_a_broken_manifest_is_listed_as_unreadable(client: TestClient, scan: Path) -> None:
    (scan / ".loops" / "scan" / "loop.json").write_text('{"id": "scan", "protocol": 9}')

    page = client.get("/")

    assert (
        page.status_code == 200 and "unreadable" in page.text and "protocol 9 is not supported" in page.text
    )


# ---- starting a loop ----


def start_command(repo: Path, helper: types.ModuleType, command: str | None) -> None:
    commands = {"start": command} if command else {}
    helper.register("scan", {"title": "Market scan", "commands": commands}, repo)


def start_form(client: TestClient, repo: Path, *, confirm: bool = True, again: bool = True) -> dict[str, str]:
    """What the Start button sends: the token, the command the page showed and, the first time, the tick.

    The loop of these tests has a round under way that the board did not start, so the form also
    carries the tick for a second copy unless a test leaves it out."""
    form = {"token": token_of(client), "command": store.read_manifest(repo, "scan").commands.get("start", "")}
    return form | ({"confirm": "yes"} if confirm else {}) | ({"again": "yes"} if again else {})


def wait_until_ended(client: TestClient) -> None:
    for _ in range(100):
        if "Running since" not in client.get("/loop/some-repo/scan").text:
            return
        time.sleep(0.05)
    raise AssertionError("the started process did not end")


def test_start_runs_the_declared_command_in_the_repository_and_shows_its_output(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    script = "import pathlib; pathlib.Path('started.txt').write_text('yes'); print('hello from the loop')"
    start_command(scan, helper, f'{sys.executable} -c "{script}"')

    started = client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    wait_until_ended(client)

    assert "note=Started" in started.headers["location"]
    assert (scan / "started.txt").read_text() == "yes"
    assert "hello from the loop" in client.get("/loop/some-repo/scan").text


def test_start_is_refused_without_a_declared_command_and_while_one_runs(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, None)
    none = client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    assert "no%20start%20command" in none.headers["location"]

    start_command(scan, helper, f'{sys.executable} -c "import time; time.sleep(30)"')
    client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    again = client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    assert "already%20running" in again.headers["location"]
    assert 'class="pill running"' in client.get("/loop/some-repo/scan").text

    ended = client.post("/loop/some-repo/scan/kill", data={"token": token_of(client)})
    wait_until_ended(client)
    assert "told%20to%20end" in ended.headers["location"]


def test_the_first_start_of_a_command_needs_a_tick_and_later_ones_do_not(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c \"open('ran.txt', 'a').write('x')\"")
    page = client.get("/loop/some-repo/scan").text
    assert 'name="confirm"' in page and "comes from this repository" in page

    refused = client.post("/loop/some-repo/scan/start", data=start_form(client, scan, confirm=False))
    assert "first%20start" in refused.headers["location"] and not (scan / "ran.txt").exists()

    client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    wait_until_ended(client)
    assert 'name="confirm"' not in client.get("/loop/some-repo/scan").text
    client.post("/loop/some-repo/scan/start", data=start_form(client, scan, confirm=False))
    wait_until_ended(client)
    assert (scan / "ran.txt").read_text() == "xx"


def test_a_started_loop_gets_a_minimal_environment(
    client: TestClient, scan: Path, helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOARD_SECRET", "do-not-pass")
    script = "import os, json; open('env.json', 'w').write(json.dumps(sorted(os.environ)))"
    start_command(scan, helper, f'{sys.executable} -c "{script}"')

    client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    wait_until_ended(client)

    names = set(json.loads((scan / "env.json").read_text()))
    assert "BOARD_SECRET" not in names and "PATH" in names and "HOME" in names
    assert names <= {
        "PATH",
        "HOME",
        "LANG",
        "TERM",
        "LOOPCAPTAIN_INBOX_KEY",
        "LC_CTYPE",
        "__CF_USER_TEXT_ENCODING",
    }
    assert "LOOPCAPTAIN_INBOX_KEY" in names  # a loop must find the key the board signs with


def test_a_started_loop_is_told_the_key_path_even_where_the_board_was_not(
    scan: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOOPCAPTAIN_INBOX_KEY")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    env = steer.minimal_env()

    assert env["LOOPCAPTAIN_INBOX_KEY"] == str(tmp_path / "home" / ".config" / "loopcaptain" / "inbox.key")
    assert env["LOOPCAPTAIN_INBOX_KEY"] == str(signing.key_path())


def test_the_start_command_runs_without_a_shell(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c pass ; touch injected.txt")

    client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    wait_until_ended(client)

    assert not (scan / "injected.txt").exists()


# ---- which repositories are shown ----


def test_roots_show_every_sub_folder_with_a_loopcaptain_folder(tmp_path: Path, scan: Path) -> None:
    (tmp_path / "plain-repo").mkdir()
    config_file = tmp_path / "loopcaptain.local.yaml"
    config_file.write_text(f"roots:\n  - {tmp_path}\nrepos:\n  - {scan}\n")

    repos = find_repos(parse_config(config_file))

    assert [(repo.key, repo.path) for repo in repos] == [("some-repo", scan)]


def test_a_config_that_is_not_lists_of_paths_is_refused(tmp_path: Path) -> None:
    config_file = tmp_path / "loopcaptain.local.yaml"
    config_file.write_text("roots: ~/projects\n")

    with pytest.raises(StoreError, match="must be a list of paths"):
        parse_config(config_file)


def test_without_a_config_the_demo_folder_is_shown_if_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LOOPCAPTAIN_CONFIG", raising=False)
    monkeypatch.setattr("loopcaptain.board.discover.USER_CONFIG", tmp_path / "none.yaml")
    assert load_config(tmp_path) == Config()

    (tmp_path / "demo").mkdir()

    assert load_config(tmp_path).repos == ((tmp_path / "demo").resolve(),)


# ---- the picture of a round ----


def test_reviewers_share_a_column_and_the_gate_follows_them(scan: Path) -> None:
    manifest = store.read_manifest(scan, "scan")

    column = columns(manifest)
    graph = layout(manifest)

    assert column == {"plan": 0, "research": 1, "build": 2, "facts": 3, "reader": 3, "gate": 4, "verdict": 5}
    assert len(graph.edges) == 7 and graph.back
    facts, reader = (node for node in graph.nodes if node.id in ("facts", "reader"))
    assert facts.x == reader.x and facts.y < reader.y


# ---- a repository the board must not trust ----


def test_start_is_refused_when_the_command_changed_after_the_page_was_drawn(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c pass")
    seen = start_form(client, scan)
    start_command(scan, helper, f"{sys.executable} -c \"open('swapped.txt', 'w')\"")

    refused = client.post("/loop/some-repo/scan/start", data=seen)

    assert "command%20changed" in refused.headers["location"]
    assert not (scan / "swapped.txt").exists()


def test_an_inbox_that_is_a_link_to_another_file_is_not_written(client: TestClient, scan: Path) -> None:
    target = scan.parent / "elsewhere.txt"
    target.write_text("mine\n")
    (scan / ".loops" / "scan" / "inbox.jsonl").symlink_to(target)

    sent = client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})

    assert "cannot%20be%20written" in sent.headers["location"]
    assert target.read_text() == "mine\n"


def test_a_loop_folder_that_is_a_link_is_not_listed(scan: Path) -> None:
    outside = scan.parent / "outside-loop"
    outside.mkdir()
    (outside / "loop.json").write_text('{"id": "linked"}')
    (scan / ".loops" / "linked").symlink_to(outside)

    assert store.loop_ids(scan) == ["scan"]


def test_a_log_that_is_not_a_plain_file_or_is_huge_is_refused_not_read(
    client: TestClient, scan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    events = scan / ".loops" / "scan" / "events.jsonl"
    monkeypatch.setattr(store, "MAX_LOG_BYTES", 10)
    assert "over the" in client.get("/").text

    events.unlink()
    os.mkfifo(events)

    page = client.get("/")
    assert page.status_code == 200 and "not a regular file" in page.text


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".env",
        ".env.local",
        "sub/.git/HEAD",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        ".docker/config.json",
        ".kube/config",
        "certs/server.pem",
        "deploy.key",
        "id_rsa",
        "keys/id_ed25519.pub",
        "credentials-prod.json",
        "secrets.yaml",
        "certs/client.p12",
        "infra/terraform.tfstate",
        "infra/terraform.tfstate.backup",
        ".htpasswd",
        "service-account-prod.json",
    ],
)
def test_git_and_secret_files_are_never_shown(client: TestClient, scan: Path, path: str) -> None:
    (scan / path).parent.mkdir(parents=True, exist_ok=True)
    (scan / path).write_text("secret")

    assert client.get("/loop/some-repo/scan/file", params={"path": path}).status_code == 404


def test_a_file_that_is_not_known_text_is_named_not_shown(client: TestClient, scan: Path) -> None:
    (scan / "dump.bin").write_text("looks like text but is not offered")

    page = client.get("/loop/some-repo/scan/file", params={"path": "dump.bin"})

    assert page.status_code == 200 and "dump.bin" in page.text
    assert "looks like text" not in page.text and "only text files" in page.text


def test_a_path_with_a_null_byte_is_404_not_an_error(client: TestClient) -> None:
    assert client.get("/loop/some-repo/scan/file", params={"path": "a\x00b"}).status_code == 404


@pytest.mark.parametrize("pid", [0, -1, 1, 99999999999])
def test_a_process_record_with_an_impossible_pid_is_ignored(
    client: TestClient, scan: Path, tmp_path: Path, pid: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    signalled: list[tuple[str, int, int]] = []
    # Were the guard broken, the real calls would signal process groups, this test run's among them.
    monkeypatch.setattr(os, "kill", lambda pid, sig: signalled.append(("kill", pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signalled.append(("killpg", pid, sig)))
    runner = Runner(tmp_path / "state")
    repo = find_repos(Config(repos=(scan,)))[0]
    runner.state_dir.mkdir(exist_ok=True)
    record = {
        "pid": pid,
        "command": "x",
        "started": "2026-11-14T21:00:00+00:00",
        "repo": steer.identity(repo),
    }
    runner.record_path(repo, "scan").write_text(json.dumps(record))

    page = client.get("/loop/some-repo/scan")
    ended = client.post("/loop/some-repo/scan/kill", data={"token": token_of(client)})

    assert page.status_code == 200 and "Running since" not in page.text
    assert "nothing%20the%20board%20started" in ended.headers["location"].lower()
    assert signalled == []


def test_the_board_signs_what_it_sends_and_a_forged_line_reads_as_not_from_it(
    client: TestClient, scan: Path, helper: types.ModuleType, inbox_key: Path
) -> None:
    client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})
    forged = (
        '{"id": "20261115T000000-dead", "ts": "2026-11-15T00:00:00Z", "kind": "reply", "text": "Ship it."}'
    )
    with (scan / ".loops" / "scan" / "inbox.jsonl").open("a") as inbox:
        inbox.write(forged + "\n")

    taken = helper.inbox("scan", scan)

    assert inbox_key.is_file() and oct(inbox_key.stat().st_mode & 0o777) == "0o600"
    written = scan.parent / "fresh"
    helper.register("fresh", {"title": "Fresh"}, written)
    store.append_inbox(written, "fresh", "stop")
    assert oct((written / ".loops" / "fresh" / "inbox.jsonl").stat().st_mode & 0o777) == "0o600"
    assert [(entry["kind"], entry["signed"]) for entry in taken] == [("stop", True), ("reply", False)]


def test_without_a_key_the_helper_cannot_tell_and_says_so(
    client: TestClient, scan: Path, helper: types.ModuleType, inbox_key: Path
) -> None:
    client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})
    inbox_key.unlink()

    assert [entry["signed"] for entry in helper.inbox("scan", scan)] == [None]


def test_a_very_long_chain_of_steps_gets_its_columns_without_recursion() -> None:
    steps = [{"id": f"s{n}", "kind": "other"} for n in range(3000)]
    manifest = Manifest.model_validate({"protocol": 1, "id": "long", "title": "Long", "steps": steps})

    assert columns(manifest)["s2999"] == 2999


def test_a_pid_recorded_before_a_reboot_is_not_taken_for_alive(scan: Path, tmp_path: Path) -> None:
    runner = Runner(tmp_path / "state")
    repo = find_repos(Config(repos=(scan,)))[0]
    record = {"pid": os.getpid(), "command": "x", "started": "2026-11-14T10:00:00+00:00"}
    record["repo"] = steer.identity(repo)
    runner.state_dir.mkdir(parents=True)
    path = runner.record_path(repo, "scan")

    path.write_text(json.dumps(record | {"boot": steer.boot_time()}))
    alive_now = runner.process(repo, "scan")
    path.write_text(json.dumps(record | {"boot": steer.boot_time() - 86_400}))
    before_reboot = runner.process(repo, "scan")

    assert alive_now is not None and alive_now.alive
    assert before_reboot is not None and not before_reboot.alive


def test_a_pid_now_held_by_a_process_started_later_is_not_taken_for_alive(scan: Path, tmp_path: Path) -> None:
    """The same boot, the same pid, another process: its start time tells, so End signals nothing."""
    runner = Runner(tmp_path / "state")
    repo = find_repos(Config(repos=(scan,)))[0]
    mine = steer.process_start_time(os.getpid())
    record = {
        "pid": os.getpid(),
        "command": "x",
        "started": "2026-11-14T10:00:00+00:00",
        "boot": steer.boot_time(),
    }
    record["repo"] = steer.identity(repo)
    runner.state_dir.mkdir(parents=True)
    path = runner.record_path(repo, "scan")

    path.write_text(json.dumps(record | {"process_start": mine}))
    same = runner.process(repo, "scan")
    path.write_text(json.dumps(record | {"process_start": (mine or 0) - 3600}))
    reused = runner.process(repo, "scan")

    assert mine is not None and steer.boot_time() - 5 < mine <= time.time()
    assert same is not None and same.alive
    assert reused is not None and not reused.alive
    with pytest.raises(StoreError, match="nothing the board started"):
        runner.kill(repo, "scan")


def test_a_process_that_is_gone_has_no_start_time() -> None:
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()

    assert steer.process_start_time(gone.pid) is None


def test_the_board_records_when_the_process_it_started_began(scan: Path, tmp_path: Path) -> None:
    runner = Runner(tmp_path / "state")
    repo = find_repos(Config(repos=(scan,)))[0]
    manifest = Manifest.model_validate_json((scan / ".loops" / "scan" / "loop.json").read_text())
    command = f"{sys.executable} -c 'import time; time.sleep(5)'"
    manifest = manifest.model_copy(update={"commands": {**manifest.commands, "start": command}})

    before = time.time()
    process = runner.start(repo, manifest)
    record = json.loads(runner.record_path(repo, "scan").read_text())
    runner.kill(repo, "scan")

    assert process.alive and before - 2 <= record["process_start"] <= time.time()


def test_worktrees_of_one_repository_show_once_from_the_last_written(
    tmp_path: Path, helper: types.ModuleType
) -> None:
    root = tmp_path / "work"
    main_checkout, worktree = root / "tool", root / "tool-loop"
    (main_checkout / ".git" / "worktrees" / "tool-loop").mkdir(parents=True)
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main_checkout}/.git/worktrees/tool-loop\n")
    (main_checkout / ".git" / "worktrees" / "tool-loop" / "gitdir").write_text(f"{worktree}/.git\n")
    helper.register("scan", {"title": "Old copy"}, worktree)
    time.sleep(0.01)
    helper.register("scan", {"title": "Fresh copy"}, main_checkout)

    repos = find_repos(Config(roots=(root,)))

    assert [(repo.path, repo.others) for repo in repos] == [(main_checkout, (worktree,))]


def test_the_loop_page_says_which_worktree_it_reads(tmp_path: Path, helper: types.ModuleType) -> None:
    root = tmp_path / "work"
    main_checkout, worktree = root / "tool", root / "tool-loop"
    (main_checkout / ".git" / "worktrees" / "tool-loop").mkdir(parents=True)
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main_checkout}/.git/worktrees/tool-loop\n")
    (main_checkout / ".git" / "worktrees" / "tool-loop" / "gitdir").write_text(f"{worktree}/.git\n")
    helper.register("scan", {"title": "Old copy"}, worktree)
    time.sleep(0.01)
    helper.register("scan", {"title": "Fresh copy"}, main_checkout)
    app = create_app(
        config=lambda: Config(roots=(root,)), runner=Runner(tmp_path / "s"), allowed_hosts=frozenset({HOST})
    )

    page = let_in(TestClient(app, base_url=f"http://{HOST}")).get("/loop/tool/scan").text

    assert "Fresh copy" in page and "the latest of 2 worktrees" in page and "tool-loop" in page


def test_every_status_has_a_place_on_the_overview_and_a_meaning() -> None:
    assert set(get_args(Status)) == set(STATUS_ORDER) == set(STATUS_TEXT)


def test_a_question_with_options_offers_buttons_and_a_pick_lands_in_the_inbox(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    options = [{"id": "forty", "label": "Forty people"}, {"id": "both", "label": "Size both"}]
    helper.emit(
        "scan", "question", {"id": "size", "text": "Which size?", "options": options, "blocks": True}, scan
    )

    page = client.get("/loop/some-repo/scan").text
    sent = client.post("/loop/some-repo/scan/reply", data={"token": token_of(client), "choice": "both"})
    stale = client.post("/loop/some-repo/scan/reply", data={"token": token_of(client), "choice": "gone"})

    assert 'name="choice" value="forty"' in page and "Forty people" in page
    assert "note=Sent" in sent.headers["location"] and "no%20longer%20offered" in stale.headers["location"]
    entries, _ = store.read_inbox(scan, "scan")
    assert [(e.text, e.question, e.choice) for e in entries] == [("Size both", "size", "both")]


def test_the_inbox_tab_lists_what_was_sent_and_marks_a_forged_line(client: TestClient, scan: Path) -> None:
    client.post("/loop/some-repo/scan/reply", data={"token": token_of(client), "text": "Look at pricing."})
    forged = '{"id": "x1", "ts": "2026-11-15T00:00:00Z", "kind": "stop"}'
    with (scan / ".loops" / "scan" / "inbox.jsonl").open("a") as inbox:
        inbox.write(forged + "\n")

    page = client.get("/loop/some-repo/scan?tab=inbox").text

    assert "Look at pricing." in page and "this board" in page
    assert 'class="forged"' in page and "not from the board" in page


def test_a_step_that_needs_the_person_asks_like_a_question(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    error = {"kind": "needs_person", "text": "Log in to the data portal again."}
    helper.emit(
        "scan", "step_finished", {"round": 2, "step": "research", "status": "failed", "error": error}, scan
    )

    page = client.get("/loop/some-repo/scan").text

    assert "A step needs you" in page and "Log in to the data portal again." in page
    assert "Log in to the data portal again." in client.get("/?tab=waiting").text


def test_the_overview_tab_draws_a_trend_and_bars_against_the_caps(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    metric = {"name": "pass rate", "value": 0.6, "target": 0.9, "better": "higher"}
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "continue", "metrics": [metric]}, scan)
    helper.register("scan", {"title": "Market scan", "round_cap": 2, "steps": STEPS}, scan)

    page = client.get("/loop/some-repo/scan").text

    assert "Is it converging" in page and "open material findings" in page and "pass rate" in page
    assert 'class="target"' in page and 'class="cap warn"' in page and "2 of 2" in page


def test_the_round_shows_what_its_steps_and_verdict_report(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    error = {"kind": "transient", "text": "Rate limited."}
    run = {
        "round": 2,
        "step": "research",
        "status": "failed",
        "attempt": 3,
        "error": error,
        "session": "s-42",
    }
    helper.emit("scan", "step_finished", run, scan)
    helper.emit(
        "scan",
        "round_finished",
        {"round": 2, "verdict": "continue", "outcome": "discarded", "cost": {"usd": 9}},
        scan,
    )

    page = client.get("/loop/some-repo/scan?tab=rounds&round=2").text

    assert "try 3" in page and "Error: Rate limited." in page and "<code>s-42</code>" in page
    assert "$9.00 for the round" in page and ">discarded<" in page


def test_a_step_shows_the_model_it_really_ran_on(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.emit(
        "scan", "step_finished", {"round": 2, "step": "research", "attempt": 2, "model": "small"}, scan
    )

    page = client.get("/loop/some-repo/scan?tab=rounds&round=2").text

    assert "model <code>small</code>" in page


def test_a_trend_is_called_better_only_where_the_loop_says_which_way_is_better() -> None:
    rising = trend.chart(trend.Series("cost", ((1, 1.0), (2, 3.0)), unit="$"))
    falling = trend.chart(trend.Series("open", ((1, 4.0), (2, 1.0)), better="lower"))

    assert rising.improving is None and falling.improving is True


def test_stop_is_offered_only_where_a_loop_may_still_start_a_round(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    assert "Stop after this round" in client.get("/loop/some-repo/scan").text

    helper.emit("scan", "round_finished", {"round": 2, "verdict": "done"}, scan)
    page = client.get("/loop/some-repo/scan").text

    assert "Stop after this round" not in page and "Stop before the next round" not in page
    assert "names no command the board could start" in page


def test_a_stalled_loop_says_what_it_last_did_and_what_to_do(
    scan: Path, helper: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    later = datetime.now(UTC) + timedelta(hours=5)
    monkeypatch.setattr("loopcaptain.board.discover.now", lambda: later)
    app = create_app(
        config=lambda: Config(repos=(scan,)), runner=Runner(tmp_path / "s"), allowed_hosts=frozenset({HOST})
    )

    page = let_in(TestClient(app, base_url=f"http://{HOST}")).get("/loop/some-repo/scan").text

    assert 'class="pill stalled"' in page and "Why this loop looks stalled" in page
    assert "The last line was <b>" in page and "If it died, start it again" in page


def test_a_loop_that_cannot_be_read_gets_a_page_with_the_fix(client: TestClient, scan: Path) -> None:
    manifest = scan / ".loops" / "scan" / "loop.json"
    manifest.write_text('{"protocol": 1, "id": "scan", "round_cap": "many"}')

    page = client.get("/loop/some-repo/scan")

    assert page.status_code == 200 and "cannot be read" in page.text
    assert "round_cap" in page.text and "loopcaptain validate" in page.text


def test_the_loop_page_shows_what_validate_finds(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "step_finished", {"round": 2, "step": "facts", "artifact": "gone.md"}, scan)

    page = client.get("/loop/some-repo/scan").text

    assert "What the protocol check finds" in page and "gone.md does not exist" in page


def test_the_overview_filters_by_text_and_status_and_folds_finished_loops(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.register("done-one", {"title": "Finished survey"}, scan)
    helper.emit("done-one", "round_started", {"round": 1}, scan)
    helper.emit("done-one", "round_finished", {"round": 1, "verdict": "done"}, scan)

    default = client.get("/").text
    shown = client.get("/?finished=1").text
    found = client.get("/?q=market").text
    by_status = client.get("/?status=done").text

    assert (
        "Market scan" in default
        and "Finished survey" not in default
        and "1 finished loop folded away" in default
    )
    assert "loops in 1 project<" in default
    assert "Finished survey" in shown
    assert "Market scan" in found and "Finished survey" not in found
    assert "Finished survey" in by_status and "Market scan" not in by_status


def test_a_fresh_board_offers_the_two_prompts_and_the_demo(tmp_path: Path) -> None:
    app = create_app(config=lambda: Config(), runner=Runner(tmp_path / "s"), allowed_hosts=frozenset({HOST}))

    page = let_in(TestClient(app, base_url=f"http://{HOST}")).get("/").text

    assert "Help me build an agent loop" in page and "Help me see and steer" in page
    assert "loopcaptain demo" in page


def test_the_title_counts_what_waits(client: TestClient, scan: Path, helper: types.ModuleType) -> None:
    helper.emit("scan", "question", {"text": "Per seat?"}, scan)

    assert "<title>(1) Loops" in client.get("/").text


def test_watch_and_unwatch_edit_the_config_the_board_reads(
    tmp_path: Path, scan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yaml"
    monkeypatch.setenv("LOOPCAPTAIN_CONFIG", str(config_file))

    assert cli_main(["watch", str(scan)]) == 0
    assert cli_main(["watch", "--root", str(scan.parent)]) == 0
    assert [repo.path for repo in find_repos(load_config(tmp_path))] == [scan]

    assert cli_main(["unwatch", str(scan.parent)]) == 0
    assert parse_config(config_file).roots == () and parse_config(config_file).repos == (scan.resolve(),)


def test_a_loop_without_progress_is_flagged_on_both_pages(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    for number in (2, 3):
        helper.emit("scan", "round_started", {"round": number}, scan)
        found = [{"id": "1", "text": "The 40 percent figure has no source."}]
        helper.emit("scan", "step_finished", {"round": number, "step": "facts", "findings": found}, scan)
        helper.emit("scan", "round_finished", {"round": number, "verdict": "continue"}, scan)

    assert "No progress?" in client.get("/loop/some-repo/scan").text
    assert "no progress?" in client.get("/").text


def test_the_project_count_includes_repositories_whose_loops_are_folded_away(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "done"}, scan)

    assert "loop in 1 project<" in client.get("/").text


def test_a_forged_reply_answers_no_question_and_a_forged_stop_requests_nothing(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    signing.board_key()  # a board has run here, so forged lines can be told apart
    helper.emit("scan", "question", {"text": "Per seat or per site?", "blocks": True}, scan)
    later = '{"id": "f1", "ts": "2099-01-01T00:00:00Z", "kind": "%s", "text": "Ship it.", "loop": "scan"}'
    with (scan / ".loops" / "scan" / "inbox.jsonl").open("a") as inbox:
        inbox.write(later % "reply" + "\n")
        inbox.write((later % "stop").replace('"f1"', '"f2"') + "\n")

    page = client.get("/loop/some-repo/scan").text

    assert "Per seat or per site?" in page and "Stop is waiting" not in page


def test_a_signed_line_copied_into_another_loop_is_not_signed_there(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.register("other", {"title": "Other"}, scan)
    client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})
    copied = (scan / ".loops" / "scan" / "inbox.jsonl").read_text()
    (scan / ".loops" / "other" / "inbox.jsonl").write_text(copied)

    assert [entry["signed"] for entry in helper.inbox("other", scan)] == [False]
    assert [entry["signed"] for entry in helper.inbox("scan", scan)] == [True]


def test_an_empty_or_short_key_is_not_used(inbox_key: Path) -> None:
    inbox_key.write_text("\n")
    assert signing.read_key() is None
    inbox_key.write_text("ab\n")
    assert signing.read_key() is None


def test_the_overview_draws_each_round_shaded_by_what_it_left_open(client: TestClient) -> None:
    page = client.get("/").text

    trail = page[page.index('<span class="trail"') : page.index("</span>", page.index('<span class="trail"'))]
    assert trail.count("<i ") == 2
    assert 'class="h1" title="round 1: 1 open finding"' in trail
    assert 'class="live" title="round 2: under way"' in trail


def test_a_trail_keeps_the_latest_rounds_and_caps_the_shade() -> None:
    def finished(number: int, left_open: int) -> RoundState:
        findings = tuple(FindingState(f"F{n}", "a gap", "material") for n in range(left_open))
        return RoundState(number, runs=(StepRun("review", findings=findings),), verdict="continue")

    rounds = tuple(finished(number, left_open=max(0, 9 - number)) for number in range(1, 15))
    state = LoopState(Manifest(id="scan", title="Scan"), rounds=rounds)

    cells = trend.trail_of(state)

    assert [cell.number for cell in cells] == list(range(3, 15))
    assert cells[0].look == "h4" and cells[0].label == "round 3: 6 open findings"
    assert cells[5].look == "h1" and cells[-1].look == "clear"


# ---- where the board keeps its own records ----


def test_the_state_folder_is_the_users_own_unless_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LOOPCAPTAIN_STATE", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    plain = steer.state_home()
    monkeypatch.setenv("XDG_STATE_HOME", "relative/ignored")
    relative = steer.state_home()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    xdg = Runner().state_dir
    monkeypatch.setenv("LOOPCAPTAIN_STATE", str(tmp_path / "named"))
    named = Runner().state_dir

    assert plain == relative == tmp_path / "home" / ".local" / "state" / "loopcaptain"
    assert (xdg, named) == (tmp_path / "xdg" / "loopcaptain", tmp_path / "named")


def test_records_in_the_folder_the_board_is_started_in_are_not_read(
    scan: Path, tmp_path: Path, helper: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_command(scan, helper, "run-me")
    repo = find_repos(Config(repos=(scan,)))[0]
    planted = Runner(scan / ".state")
    planted.confirm(repo, "run-me")
    record = {"pid": os.getpid(), "command": "run-me", "started": "2026-11-14T21:00:00+00:00"}
    record["repo"] = steer.identity(repo)
    planted.record_path(repo, "scan").write_text(json.dumps(record))
    monkeypatch.chdir(scan)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LOOPCAPTAIN_STATE", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    runner = Runner()

    assert planted.is_confirmed(repo, "run-me") and planted.process(repo, "scan") is not None
    assert not runner.is_confirmed(repo, "run-me") and runner.process(repo, "scan") is None


def test_the_state_folder_and_its_files_are_the_users_alone(
    scan: Path, tmp_path: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c pass")
    repo = find_repos(Config(repos=(scan,)))[0]
    runner = Runner(tmp_path / "fresh" / "state")

    runner.start(repo, store.read_manifest(scan, "scan"))
    runner.confirm(repo, "x")

    modes = {path.name: path.stat().st_mode & 0o777 for path in runner.state_dir.iterdir()}
    assert runner.state_dir.stat().st_mode & 0o777 == 0o700
    assert set(modes.values()) == {0o600} and len(modes) == 3


def test_the_state_folder_is_made_the_users_alone_by_whichever_write_comes_first(
    scan: Path, tmp_path: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c pass")
    repo = find_repos(Config(repos=(scan,)))[0]
    confirmed_first, started_first = Runner(tmp_path / "a" / "state"), Runner(tmp_path / "b" / "state")

    confirmed_first.confirm(repo, "x")
    started_first.start(repo, store.read_manifest(scan, "scan"))

    for runner in (confirmed_first, started_first):
        assert runner.state_dir.stat().st_mode & 0o777 == 0o700, runner.state_dir


def test_a_record_made_for_a_repository_of_the_same_name_elsewhere_is_not_this_loops(
    scan: Path, tmp_path: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c pass")
    repo = find_repos(Config(repos=(scan,)))[0]
    runner = Runner(tmp_path / "state")
    runner.start(repo, store.read_manifest(scan, "scan"))
    path = runner.record_path(repo, "scan")
    own = runner.process(repo, "scan")

    path.write_text(json.dumps({**json.loads(path.read_text()), "repo": str(tmp_path / "elsewhere")}))

    assert own is not None and runner.process(repo, "scan") is None


def test_two_repositories_of_one_name_keep_their_own_process_and_log(
    tmp_path: Path, helper: types.ModuleType
) -> None:
    runner, other_board = Runner(tmp_path / "state"), Runner(tmp_path / "state")
    repos = []
    for parent, word in (("x", "first"), ("y", "second")):
        path = tmp_path / parent / "app"
        helper.register("scan", {"title": "Scan"}, path)
        start_command(path, helper, f"{sys.executable} -c \"print('{word}')\"")
        repos.append(Repo("app", path))

    runner.start(repos[0], store.read_manifest(repos[0].path, "scan"))
    other_board.start(repos[1], store.read_manifest(repos[1].path, "scan"))
    for child in (*runner.children.values(), *other_board.children.values()):
        child.wait(timeout=10)

    assert runner.record_path(repos[0], "scan") != runner.record_path(repos[1], "scan")
    assert runner.record_path(repos[0], "scan").name.startswith("app-")
    assert "first" in runner.log_tail(repos[0], "scan") and "second" not in runner.log_tail(repos[0], "scan")
    first, second = runner.process(repos[0], "scan"), runner.process(repos[1], "scan")
    assert first is not None and second is not None and first.pid != second.pid


def test_the_board_keeps_its_process_when_it_reads_the_loop_from_another_worktree(
    tmp_path: Path, helper: types.ModuleType
) -> None:
    root = tmp_path / "work"
    main_checkout, worktree = root / "tool", root / "tool-loop"
    (main_checkout / ".git" / "worktrees" / "tool-loop").mkdir(parents=True)
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main_checkout}/.git/worktrees/tool-loop\n")
    (main_checkout / ".git" / "worktrees" / "tool-loop" / "gitdir").write_text(f"{worktree}/.git\n")
    for path in (main_checkout, worktree):
        helper.register("scan", {"title": "Scan"}, path)
        start_command(path, helper, f"{sys.executable} -c 'import time; time.sleep(30)'")
    runner = Runner(tmp_path / "state")
    started = runner.start(Repo("tool", main_checkout), store.read_manifest(main_checkout, "scan"))
    try:
        flipped = runner.process(Repo("tool", worktree), "scan")
        assert flipped is not None and flipped.pid == started.pid and flipped.alive
    finally:
        runner.kill(Repo("tool", worktree), "scan")


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_a_record_keeps_its_name_when_the_board_reads_another_worktree(tmp_path: Path) -> None:
    main = tmp_path / "tool"
    main.mkdir()
    git("init", "-q", cwd=main)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x", cwd=main)
    git("worktree", "add", "-q", str(tmp_path / "tool-loop"), cwd=main)
    runner = Runner(tmp_path / "state")
    before = runner.name(Repo("tool", main), "scan")
    after = runner.name(Repo("tool-loop", tmp_path / "tool-loop"), "scan")
    assert before == after
    assert before.startswith("tool-")


# ---- a page that is left open ----


def test_an_open_page_learns_that_its_loop_went_quiet_without_any_file_changing(
    client: TestClient, scan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def later(minutes: int) -> datetime:
        return datetime.now(UTC) + timedelta(minutes=minutes)

    drawn = client.get("/loop/some-repo/scan").text
    pulses = []
    for minutes in (1, 44, 46, 600):
        monkeypatch.setattr(store, "now", lambda minutes=minutes: later(minutes))
        pulses.append((client.get("/loop/some-repo/scan/pulse").json(), client.get("/pulse").json()))
    monkeypatch.setattr("loopcaptain.board.discover.now", lambda: later(46))
    reloaded = client.get("/loop/some-repo/scan").text

    assert pulses[0] == pulses[1] and pulses[2] == pulses[3]
    assert pulses[1][0] != pulses[2][0] and pulses[1][1] != pulses[2][1]
    assert f'data-pulse="{pulses[0][0]["pulse"]}"' in drawn
    assert 'class="pill running"' in drawn and 'class="pill stalled"' in reloaded


# ---- a Stop nothing would read, a Start beside a loop that runs ----


@pytest.mark.parametrize("verdict", ["done", "failed", "stopped"])
def test_a_stop_for_a_loop_that_starts_no_further_round_is_not_taken(
    client: TestClient, scan: Path, helper: types.ModuleType, verdict: str
) -> None:
    helper.emit("scan", "round_finished", {"round": 2, "verdict": verdict}, scan)

    sent = client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})
    page = client.get(sent.headers["location"]).text

    assert f"No stop was sent: this loop is {verdict}" in page and 'class="flash bad"' in page
    assert store.read_inbox(scan, "scan") == ([], [])


def test_a_stop_for_a_loop_between_rounds_is_still_taken(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "continue"}, scan)

    sent = client.post("/loop/some-repo/scan/stop", data={"token": token_of(client)})

    assert "note=Stop%20sent" in sent.headers["location"]
    assert [entry.kind for entry in store.read_inbox(scan, "scan")[0]] == ["stop"]


def test_start_beside_a_loop_that_runs_without_the_board_needs_its_own_tick(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c \"open('started','w').write('x')\"")
    page = client.get("/loop/some-repo/scan").text

    refused = client.post("/loop/some-repo/scan/start", data=start_form(client, scan, again=False))
    untouched = not (scan / "started").exists()
    started = client.post("/loop/some-repo/scan/start", data=start_form(client, scan))
    wait_until_ended(client)

    assert 'name="again"' in page and "the board did not start it" in page
    assert "did%20not%20start%20it" in refused.headers["location"] and untouched
    assert "note=Started" in started.headers["location"] and (scan / "started").exists()


def test_start_of_a_loop_that_is_not_under_way_asks_for_no_second_tick(
    client: TestClient, scan: Path, helper: types.ModuleType
) -> None:
    start_command(scan, helper, f"{sys.executable} -c pass")
    helper.emit("scan", "round_finished", {"round": 2, "verdict": "done"}, scan)

    page = client.get("/loop/some-repo/scan").text
    started = client.post("/loop/some-repo/scan/start", data=start_form(client, scan, again=False))
    wait_until_ended(client)

    assert 'name="again"' not in page and "note=Started" in started.headers["location"]


# ---- the stylesheet's rules for a phone and for links ----


def test_the_stylesheet_wraps_long_labels_and_underlines_links_in_text(client: TestClient) -> None:
    sheet = client.get("/static/style.css").text
    choices = re.findall(r"form\.choices button \{[^}]*\}", sheet)
    wrapped = re.search(r"main p, main li,[^{]*\{ overflow-wrap: anywhere; \}", sheet)
    underlined = re.search(r"main p a, main li a,[^{]*\.card a[^{]*\{ text-decoration: underline;", sheet)

    assert any("white-space: normal" in rule and "max-width: 100%" in rule for rule in choices)
    assert wrapped is not None and "table.loops td.goal" in wrapped.group(0)
    assert underlined is not None and ".note a" in underlined.group(0)


# ---- guards that each need a test of their own ----


def test_every_page_tells_the_browser_not_to_guess_refer_or_keep(client: TestClient) -> None:
    for path in ("/", "/loop/some-repo/scan", "/connect", "/pulse", "/loop/some-repo/ghost"):
        headers = client.get(path).headers

        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["referrer-policy"] == "no-referrer", path
        assert headers["cache-control"] == "no-store", path
        assert "frame-ancestors 'none'" in headers["content-security-policy"], path


def test_a_file_over_the_size_the_board_renders_is_named_not_read(client: TestClient, scan: Path) -> None:
    from loopcaptain.board.files import MAX_FILE_BYTES

    (scan / "huge.md").write_text("# Marker of the huge file\n" + "x" * MAX_FILE_BYTES)
    (scan / "fits.md").write_text("# Marker of the small file\n" + "x" * (MAX_FILE_BYTES - 100))

    huge = client.get("/loop/some-repo/scan/file", params={"path": "huge.md"}).text
    fits = client.get("/loop/some-repo/scan/file", params={"path": "fits.md"}).text

    assert "too large to show here" in huge and "Marker of the huge file" not in huge
    assert "Marker of the small file" in fits


def test_a_reply_over_the_longest_the_board_sends_is_not_sent(client: TestClient, scan: Path) -> None:
    from loopcaptain.board.app import MAX_REPLY_CHARS

    form = {"token": token_of(client), "text": "x" * (MAX_REPLY_CHARS + 1)}
    refused = client.post("/loop/some-repo/scan/reply", data=form)
    inbox_after_refusal = store.read_inbox(scan, "scan")[0]
    sent = client.post("/loop/some-repo/scan/reply", data=form | {"text": "x" * MAX_REPLY_CHARS})

    assert f"over%20{MAX_REPLY_CHARS}%20characters" in refused.headers["location"]
    assert inbox_after_refusal == [] and "note=Sent" in sent.headers["location"]


def test_a_remembered_pid_that_is_someone_elses_process_now_is_not_alive(
    scan: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def not_yours(pid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    runner = Runner(tmp_path / "state")
    repo = find_repos(Config(repos=(scan,)))[0]
    record = {"pid": 4242, "command": "x", "started": "2026-11-14T21:00:00+00:00", "boot": steer.boot_time()}
    record["repo"] = steer.identity(repo)
    steer.write_private(runner.record_path(repo, "scan"), json.dumps(record))
    monkeypatch.setattr(os, "kill", not_yours)

    process = runner.process(repo, "scan")

    assert process is not None and process.pid == 4242 and not process.alive
    with pytest.raises(StoreError, match="nothing the board started"):
        runner.kill(repo, "scan")


def test_the_pulse_of_a_loop_without_files_is_steady_and_changes_when_one_appears(scan: Path) -> None:
    (scan / ".loops" / "bare").mkdir()

    before = store.fingerprint(scan, "bare")
    again = store.fingerprint(scan, "bare")
    (scan / ".loops" / "bare" / "events.jsonl").write_text("{}\n")

    assert before == again == "0.0.0.quiet" and store.fingerprint(scan, "bare") != before


# ---- a folder that says it is another repository's worktree ----


@pytest.mark.parametrize(
    "claim",
    [
        "{other}/.git/worktrees/mine",
        "{other}/.git/worktrees/theirs",
        "{other}/.git",
        "{other}/.git/modules/x",
    ],
)
def test_a_folder_that_only_claims_to_be_a_worktree_of_another_repository_stands_for_itself(
    tmp_path: Path, helper: types.ModuleType, claim: str
) -> None:
    root = tmp_path / "work"
    other, claimant = root / "tool", root / "claimant"
    (other / ".git" / "worktrees" / "theirs").mkdir(parents=True)
    (other / ".git" / "worktrees" / "theirs" / "gitdir").write_text(f"{root}/tool-loop/.git\n")
    (other / ".git" / "modules" / "x").mkdir(parents=True)
    claimant.mkdir()
    (claimant / ".git").write_text(f"gitdir: {claim.format(other=other)}\n")
    helper.register("scan", {"title": "The real one"}, other)
    time.sleep(0.01)
    helper.register("decoy", {"title": "Written last"}, claimant)

    repos = find_repos(Config(roots=(root,)))

    assert sorted((repo.key, repo.others) for repo in repos) == [("claimant", ()), ("tool", ())]
    assert store.loop_ids(next(repo.path for repo in repos if repo.key == "tool")) == ["scan"]


@pytest.mark.parametrize("stat", ["", "4242 (loop", "4242 (loop) S 1", "4242 (a) b) S " + "x " * 30])
def test_a_proc_stat_line_that_cannot_be_read_gives_no_start_time(stat: str) -> None:
    assert steer.start_ticks(stat) is None


def test_a_proc_stat_line_gives_the_ticks_after_boot_even_with_a_bracket_in_the_name() -> None:
    fields = ["S"] + [str(number) for number in range(4, 60)]  # field 3 onwards; field 22 is 22
    assert steer.start_ticks("4242 (odd) name) " + " ".join(fields)) == 22


def test_a_process_whose_start_time_cannot_be_read_is_not_called_ended_nor_signalled(
    scan: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signalled: list[int] = []
    runner = Runner(tmp_path / "state")
    repo = find_repos(Config(repos=(scan,)))[0]
    record = {
        "pid": os.getpid(),
        "command": "x",
        "started": "2026-11-14T10:00:00+00:00",
        "boot": steer.boot_time(),
    }
    record |= {"repo": steer.identity(repo), "process_start": 1_000_000.0}
    steer.write_private(runner.record_path(repo, "scan"), json.dumps(record))
    monkeypatch.setattr(steer, "process_start_time", lambda pid: None)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signalled.append(pid))

    process = runner.process(repo, "scan")

    assert process is not None and process.alive and not process.confirmed
    with pytest.raises(StoreError, match="could not confirm"):
        runner.kill(repo, "scan")
    assert signalled == []
