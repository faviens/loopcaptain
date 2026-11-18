<!-- The site's copy, docs/security.md, takes the parts between these marks and draws the pictures from its own folder. -->
<!-- --8<-- [start:head] -->
# Security

## Threat model

How a browser gets into the board, and how an answer, a stop or a start
reaches a loop:

<!-- --8<-- [end:head] -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/entry-dark.svg">
  <img alt="How a browser gets into the board: loopcaptain serve prints an address with a new key; opening it once sets a cookie of its own and leads on to the page; every request after passes the host check, the cookie and, for a form, the token, and only the entry and the static files are open without the cookie." src="docs/assets/entry-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/steer-dark.svg">
  <img alt="How steering reaches a loop: an answer or a stop is appended to the loop's inbox.jsonl as a line signed with the inbox key, which the loop's helper checks before it acts; Start runs the loop's own commands.start without a shell, with a minimal environment that names the key's path, and keeps its records in the state folder." src="docs/assets/steer-light.svg">
</picture>

<!-- --8<-- [start:model] -->
1. **Trusted:** the person at the board, the board's own config
   (`loopcaptain.local.yaml` or `~/.config/loopcaptain/config.yaml`) and its
   state folder. The state folder holds which start commands were ticked
   and which processes the board started; it is the person's own
   (`$XDG_STATE_HOME/loopcaptain`, else `~/.local/state/loopcaptain`, or
   the folder `LOOPCAPTAIN_STATE` names), never a folder inside the place
   the board is started from, and its files are readable by the user only.
2. **Not trusted:** every file in a watched repository. A loop's
   `loop.json`, `events.jsonl` and any file a loop links to may be written
   by an agent. The board reads them bounded, follows no symbolic link in
   `.loops/`, and renders content only as escaped text or Markdown
   without HTML.
   Each repository and each loop is a boundary: one the board cannot
   enter, read or make sense of is named with the reason and left out,
   and every other loop stays readable and steerable.
3. **The file viewer:** it opens text files inside a watched repository
   and nothing outside it. It never shows `.git`; of git's own files the
   board reads only the branch's name and which repository a worktree
   belongs to, from disk, without running `git`. The viewer refuses a
   block-list of names under which tools commonly keep keys, tokens and
   passwords (`PRIVATE_PARTS` and `PRIVATE_PATTERNS` in
   `src/loopcaptain/board/files.py`). The list goes by name only: a secret
   in a file with an ordinary name, such as a password in a config file,
   is shown like any other text. Watch only repositories whose text files
   may be read by everyone who can use the board.
4. **The one command it runs:** `commands.start` of a loop's `loop.json`,
   when the person presses Start, split into arguments with no shell, with
   only `PATH`, `HOME`, `LANG` and `TERM` from the board's environment,
   and `LOOPCAPTAIN_INBOX_KEY` naming the key the board signs with. The
   first start of a command for a loop needs a tick; a command with
   characters that do not show is never started, and the page names a
   script that changed since the last start. Do not put a
   folder of repositories you have not read under `roots:`.
5. **The inbox:** the board signs every line it writes with a key in
   `~/.config/loopcaptain/`, naming the loop, so a loop can tell the person
   from an agent that writes files in its repository. The board's own
   status ignores a line whose signature fails. A process with the user's
   full file access can read that key too.
6. **The network:** the board listens on `127.0.0.1` only and answers only
   to its own host name. No page loads anything from another origin.
   Nothing is sent off the machine.
7. **Who may use it:** every request, reading a page included, needs the
   session cookie that the address printed by `loopcaptain serve` sets;
   only the stylesheet, the script and the font are served without it.
   Each start makes a new key, kept in the board's memory only, so an
   address or a cookie from an earlier start is refused. Every form also
   carries a per-process token. The printed address works once: it lets
   one browser in, which stays in while that board runs, and is refused
   after that, so a copy left in a history, a scrollback or a transcript
   lets nobody in. Another browser needs a restart of `serve`.
8. **What that does not cover:** a process that runs as you and can read
   your terminal, your browser's cookie store or the board's memory can
   get in, as it can read the watched repositories and the inbox key
   directly. The boundary is between you and everything else that can
   reach the port: other accounts on the machine, a container on the host
   network, a forwarded port, a process confined to its own folder.
   A browser sends a cookie for `127.0.0.1` to every port there, so
   another web server on `127.0.0.1` that you open in the same browser
   receives the board's cookie while that board runs; the cookie, like the
   key, changes at each start.

## Reporting a vulnerability

Report privately through the repository's security advisories:
`https://github.com/faviens/loopcaptain/security/advisories/new`. Please do not open a public
issue. Expect an answer within a week.
<!-- --8<-- [end:model] -->
