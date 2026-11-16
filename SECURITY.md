# Security

## Threat model

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
   `.loops/`, never shows `.git`, `.env*` or credential files, and renders
   content only as escaped text or Markdown without HTML.
3. **The one command it runs:** `commands.start` of a loop's `loop.json`,
   when the person presses Start, split into arguments with no shell, with
   only `PATH`, `HOME`, `LANG` and `TERM` from the board's environment,
   and `LOOPCAPTAIN_INBOX_KEY` naming the key the board signs with. The
   first start of a command in a repository needs a tick. Do not put a
   folder of repositories you have not read under `roots:`.
4. **The inbox:** the board signs every line it writes with a key in
   `~/.config/loopcaptain/`, naming the loop, so a loop can tell the person
   from an agent that writes files in its repository. The board's own
   status ignores a line whose signature fails. A process with the user's
   full file access can read that key too.
5. **The network:** the board listens on `127.0.0.1` only and answers only
   to its own host name. No page loads anything from another origin.
   Nothing is sent off the machine.
6. **Who may use it:** every request, reading a page included, needs the
   session cookie that the address printed by `loopcaptain serve` sets;
   only the stylesheet, the script and the font are served without it.
   Each start makes a new key, kept in the board's memory only, so an
   address or a cookie from an earlier start is refused. Every form also
   carries a per-process token. The printed address is a password for as
   long as that board runs: do not paste it anywhere.
7. **What that does not cover:** a process that runs as you and can read
   your terminal, your browser's cookie store or the board's memory can
   get in, as it can read the watched repositories and the inbox key
   directly. The boundary is between you and everything else that can
   reach the port: other accounts on the machine, a container on the host
   network, a forwarded port, a process confined to its own folder.
   A browser sends a cookie for `127.0.0.1` to every port there, so
   another web server on `127.0.0.1` that you open in the same browser
   receives the board's cookie while that board runs; the key, and so the
   cookie, changes at each start.

## Reporting a vulnerability

Report privately through the repository's security advisories:
`https://github.com/faviens/loopcaptain/security/advisories/new`. Please do not open a public
issue. Expect an answer within a week.
