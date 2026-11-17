---
description: "Install Loopcaptain from PyPI with uv, pipx or pip, run it once through uvx, or install a tagged release from the repository."
---

# Installation

Loopcaptain is one Python package with one command, `loopcaptain`. It runs
on macOS and Linux and needs Python 3.12 or later. A loop that reports to
the board installs nothing: it writes its files, see
[Connect or build a loop](connect.md).

## Requirements

| What | Version | Why |
|---|---|---|
| Python | 3.12 or later | the board and the command line |
| [uv](https://docs.astral.sh/uv/), pipx or pip | any recent | installs the command; uv and pipx give it its own environment |
| A browser | any | the board is a local web page |

## Install the command

Loopcaptain is on [PyPI](https://pypi.org/project/loopcaptain/) as
`loopcaptain`.

=== "uv (recommended)"

    ```bash
    uv tool install loopcaptain
    ```

=== "pipx"

    ```bash
    pipx install loopcaptain
    ```

=== "pip, in a virtual environment"

    ```bash
    python3 -m venv .venv && source .venv/bin/activate
    pip install loopcaptain
    ```

Check it:

```bash
loopcaptain --version
```

To run it once without installing, `uvx loopcaptain demo` and
`uvx loopcaptain serve` do the same from a temporary environment.

## Install from the repository

A release is also a tag in the repository. Name the tag, so the install
is that release and not whatever the branch holds today:

```bash
uv tool install git+https://github.com/faviens/loopcaptain@v0.3.1
```

Without `@<tag>` the install is the `main` branch: the way to run a change
that is not released yet. It reports version `0.0.0`.

## Install from a checkout

For changing Loopcaptain itself, or for running it without installing:

```bash
git clone https://github.com/faviens/loopcaptain && cd loopcaptain
make setup          # dependencies and git hooks, through uv
make serve          # the board; open the address it prints
```

In a checkout, put `uv run` in front of every `loopcaptain` command on
these pages, or use the `make` targets (`make help` lists them).

## Upgrade and uninstall

```bash
uv tool upgrade loopcaptain
uv tool uninstall loopcaptain
```

Restart the board after an upgrade: a running board does not reload.

## What it puts on your machine

| Path | Holds | Removed by |
|---|---|---|
| `~/.config/loopcaptain/config.yaml` | the folders the board watches | deleting the file |
| `~/.config/loopcaptain/inbox.key` | the key the board signs your answers with | deleting the file; a new one is made |
| `~/.local/state/loopcaptain/` (`$XDG_STATE_HOME/loopcaptain/` where that is set) | records and logs of loops the board started, the confirmed start commands | deleting the folder |
| `~/.local/share/loopcaptain/demo/` | the example loop, after `loopcaptain demo` | deleting the folder |

Nothing else is written, nothing runs in the background, and nothing is
sent anywhere. [Security](security.md) says what the board trusts.

Next: [Get started](get-started.md).
