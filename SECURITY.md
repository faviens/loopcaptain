# Security

## Threat model

1. **Trusted:** the person at the board, the board's own config
   (`loopcaptain.local.yaml` or `~/.config/loopcaptain/config.yaml`) and its
   state folder.
2. **Not trusted:** every file in a watched repository. A loop's
   `loop.json`, `events.jsonl` and any file a loop links to may be written
   by an agent. The board reads them bounded, follows no symbolic link in
   `.loops/`, never shows `.git`, `.env*` or credential files, and renders
   content only as escaped text or Markdown without HTML.
3. **The one command it runs:** `commands.start` of a loop's `loop.json`,
   when the person presses Start, split into arguments with no shell, with
   only `PATH`, `HOME`, `LANG`, `TERM` and `LOOPCAPTAIN_INBOX_KEY` from the board's environment. The
   first start of a command in a repository needs a tick. Do not put a
   folder of repositories you have not read under `roots:`.
4. **The inbox:** the board signs every line it writes with a key in
   `~/.config/loopcaptain/`, naming the loop, so a loop can tell the person
   from an agent that writes files in its repository. The board's own
   status ignores a line whose signature fails. A process with the user's
   full file access can read that key too.
5. **The network:** the board listens on `127.0.0.1` only, answers only to
   its own host name and the names given with `--host-name` (for a proxy
   on this machine such as `tailscale serve`, which makes the board
   reachable for every device that reaches that name, Start included;
   never `tailscale funnel`, which puts it on the internet), and every form
   carries a per-process token. No page
   loads anything from another origin. The board sends nothing off the
   machine.
6. **Telegram, only when turned on:** `loopcaptain telegram` sends a
   message to the chats in `telegram.chats` when a loop needs the
   person. Telegram can read those messages: by default they carry the
   loop's name, repository, round and status only, the question and its choices only with
   `text: full`. A press or a reply is taken only from an allowed private chat and
   ends in the same checked, signed inbox line as the board's forms;
   nothing from a chat can start a loop. The bot token comes from
   `LOOPCAPTAIN_TELEGRAM_TOKEN`, is never written to a file or a log, and
   is not passed to a started loop.

## Reporting a vulnerability

Report privately through the repository's security advisories:
`https://github.com/faviens/loopcaptain/security/advisories/new`. Please do not open a public
issue. Expect an answer within a week.
