# Setup

How to set the board up for the loops on your machine: what to watch, how
to check a loop, how an agent session reports, and where to look when a
loop does not show.

## 1. Choose what the board watches

```bash
loopcaptain watch ~/projects --root     # every sub-folder with a .loops/ folder
loopcaptain watch ~/work/some-repo      # one repository
loopcaptain unwatch ~/work/some-repo
```

The commands edit `~/.config/loopcaptain/config.yaml`; you can edit it by
hand too, see [Configuration](reference/configuration.md). Worktrees of
one repository show once.

!!! warning "Watch only repositories you have read"

    The board's Start button runs the command a loop declares in its own
    `loop.json`. A folder of repositories nobody has read does not belong
    on the board.

## 2. Check each loop

```bash
loopcaptain validate ~/work/some-repo          # problems and warnings in its .loops folders
loopcaptain doctor ~/work/some-repo <loop-id>  # with the loop running: does it take a stop?
```

`validate` reads; `doctor` sends a running loop a signed stop and passes
once the loop took it and ended.

## 3. Let agent sessions report

A loop with a script needs nothing installed. A loop that an agent
session drives reports through the MCP server:

```bash
loopcaptain mcp-config <agent>      # prints the line that adds the server to your agent
```

[Works with every agent](agents.md) lists each agent.

## 4. Run the board

```bash
loopcaptain serve                   # http://127.0.0.1:8484
loopcaptain serve --port 9000
```

1. The board binds to 127.0.0.1 and accepts requests only for that host.
   It has no login because nothing outside the machine reaches it.
2. It reads the files again on every request and keeps no database. Stop
   it whenever you like; nothing is lost.
3. It runs only while you run it. To keep it up, leave it in a terminal
   or a terminal multiplexer.
4. Restart it after an upgrade.

## 5. The key your answers are signed with

The board signs every line it writes into a loop's `inbox.jsonl` with
`~/.config/loopcaptain/inbox.key`, made on first use. A loop that reads
the same key can refuse a stop or an answer the board did not write. A
loop the board starts gets the key's path as `LOOPCAPTAIN_INBOX_KEY`; a
loop you start yourself finds it in the default place.

## When a loop does not show

| What you see | Likely cause | Check |
|---|---|---|
| The repository is missing | it is not watched, or has no `.loops/` folder | `loopcaptain watch <repository>`, then reload |
| The loop shows as unreadable | `loop.json` does not follow the protocol | `loopcaptain validate <repository>` |
| `stalled` | a round is open and no line arrived for 45 minutes | the loop's own log; a loop that sleeps says so with `next_at` |
| Start is not offered | the loop declares no `commands.start` | its `loop.json` |
| Your answer is not taken | the loop does not read its inbox, or refuses an unsigned line | `loopcaptain doctor <repository> <loop-id>` |
| The port is taken | another board, or another program on 8484 | `loopcaptain serve --port <other>` |
