# Installation

Loopcaptain is one Python package with one command, `loopcaptain`. It runs
on macOS and Linux and needs Python 3.12 or later. A loop that reports to
the board installs nothing: it writes its files, see
[Connect or build a loop](connect.md).

## Requirements

| What | Version | Why |
|---|---|---|
| Python | 3.12 or later | the board and the command line |
| [uv](https://docs.astral.sh/uv/) | any recent | installs the tool into its own environment |
| A browser | any | the board is a local web page |

## Install the command

Loopcaptain is not on PyPI yet; install it from the repository.

=== "uv (recommended)"

    ```bash
    uv tool install git+https://github.com/faviens/loopcaptain
    ```

=== "pipx"

    ```bash
    pipx install git+https://github.com/faviens/loopcaptain
    ```

=== "pip, in a virtual environment"

    ```bash
    python3 -m venv .venv && source .venv/bin/activate
    pip install git+https://github.com/faviens/loopcaptain
    ```

Check it:

```bash
loopcaptain --version
```

An install from the repository's `main` branch reports `0.0.0`; a released
wheel, from the [releases page](https://github.com/faviens/loopcaptain/releases),
reports its version.

## Install from a checkout

For changing Loopcaptain itself, or for running it without installing:

```bash
git clone https://github.com/faviens/loopcaptain && cd loopcaptain
make setup          # dependencies and git hooks, through uv
make serve          # the board on http://127.0.0.1:8484
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
| `.state/` where the board starts | records and logs of loops the board started | deleting the folder |
| `~/.local/share/loopcaptain/demo/` | the example loop, after `loopcaptain demo` | deleting the folder |

Nothing else is written, nothing runs in the background, and nothing is
sent anywhere. [Security](security.md) says what the board trusts.

Next: [Get started](get-started.md).
