# Configuration

## Which repositories the board watches

A YAML file with two lists. The first found wins: the file
`LOOPCAPTAIN_CONFIG` names, `loopcaptain.local.yaml` in the folder the board
starts in, `~/.config/loopcaptain/config.yaml`. `loopcaptain watch` and
`unwatch` edit it. A `LOOPCAPTAIN_CONFIG` that names no file is an error,
not a fall-back to the next place.

```yaml
roots:       # every direct sub-folder that has a .loops/ folder is a repository
  - ~/projects
repos:       # single repositories
  - ~/work/research-loop
```

## Environment

| Variable | Default | What it sets |
|---|---|---|
| `LOOPCAPTAIN_CONFIG` | see above | the config file |
| `LOOPCAPTAIN_STATE` | `$XDG_STATE_HOME/loopcaptain`, else `~/.local/state/loopcaptain` | records and logs of loops the board started, the confirmed start commands; a second board on the machine may share it, each sees what the other started |
| `LOOPCAPTAIN_INBOX_KEY` | `~/.config/loopcaptain/inbox.key` | where the board's keys are: this file is the one key of earlier versions, and `board.key` and `keys/` lie beside it; the helper finds its loop's key from the same name |
| `LOOPCAPTAIN_MCP_ROOTS` | none | more folders, separated by `:`, under which the MCP tools may write |
