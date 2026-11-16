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

Every watched repository with a `.loops/` folder then appears on the
board's front page, grouped by repository:

![The board's front page with eight invented loops in four projects, each with its status, rounds, open findings, time and cost.](assets/screenshot-overview.webp)

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

The board shows the same on its **Connect a loop** page: the two prompts
with a Copy button, and the line for the agent you pick.

![The board's Connect a loop page: two prompts to copy, and a row of agents to pick the MCP line for.](assets/screenshot-connect.webp)

## 4. Run the board

```bash
loopcaptain serve                   # prints the address to open, port 8484
loopcaptain serve --port 9000
```

1. The board binds to 127.0.0.1 and accepts requests only for that host.
   It has no login: `serve` prints one line with the address to open,
   the number of repositories it watches and the config it read. Opening
   that address sets a session cookie in that browser; a browser without
   it sees a page that says where the address is. The key in the address
   is new at every start, so after a restart open the new address.
2. A port that is taken stops `serve` with one line that says so; start
   it with `--port <other>`.
3. It reads the files again on every request and keeps no database. Stop
   it whenever you like; nothing is lost.
4. It runs only while you run it. To keep it up, leave it in a terminal
   or a terminal multiplexer.
5. Restart it after an upgrade.

## 5. The key your answers are signed with

The board signs every line it writes into a loop's `inbox.jsonl` with
`~/.config/loopcaptain/inbox.key`, made on first use. A loop that reads
the same key can refuse a stop or an answer the board did not write. A
loop the board starts gets the key's path as `LOOPCAPTAIN_INBOX_KEY`,
whether or not the board's own environment sets it; a loop you start
yourself finds it in the default place.

## When a loop does not show

| What you see | Likely cause | Check |
|---|---|---|
| The repository is missing | it is not watched, or has no `.loops/` folder | `loopcaptain watch <repository>`, then reload |
| The loop shows as unreadable | `loop.json` does not follow the protocol | `loopcaptain validate <repository>` |
| `stalled` | a round is open and no line arrived for 45 minutes | the loop's own log; a loop that sleeps says so with `next_at` |
| Start is not offered | the loop declares no `commands.start` | its `loop.json` |
| Your answer is not taken | the loop does not read its inbox, or refuses an unsigned line | `loopcaptain doctor <repository> <loop-id>` |
| `serve` says the port cannot be used | another board, or another program on that port | `loopcaptain serve --port <other>` |
