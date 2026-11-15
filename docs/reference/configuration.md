# Configuration

## Which repositories the board watches

A YAML file with two lists. The first found wins: the file
`LOOPCAPTAIN_CONFIG` names, `loopcaptain.local.yaml` in the folder the board
starts in, `~/.config/loopcaptain/config.yaml`. `loopcaptain watch` and
`unwatch` edit it.

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
| `LOOPCAPTAIN_STATE` | `.state` where the board starts | records and logs of loops the board started, the confirmed start commands |
| `LOOPCAPTAIN_INBOX_KEY` | `~/.config/loopcaptain/inbox.key` | the key the board signs inbox lines with; the helper reads the same |
| `LOOPCAPTAIN_MCP_ROOTS` | none | more folders, separated by `:`, under which the MCP tools may write |
