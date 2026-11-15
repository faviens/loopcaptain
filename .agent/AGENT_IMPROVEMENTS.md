# Agent improvements

Evidence-backed proposals for how work in this repository is done. An
accepted one moves into its owner (AGENTS.md, a hook, a Makefile target)
and its row is deleted; the commit says where it went.

| # | Proposal | Evidence | Status |
|---|---|---|---|
| A2 | Run `ruff format` before string replacements in a file, or edit after formatting: the formatter rewraps lines and a replacement written against the old wrapping misses | Two replacement batches against `examples/demo_loop.py` failed on 2026-11-14 for this reason | open |
| A3 | Headless Chrome cannot render narrower than 500 px, so a `--window-size=390` screenshot shows a clipped desktop layout, not a phone. Check a phone with device emulation over the DevTools protocol, and make that a `make phone` target that fails when a page is wider than 390 px | The clipped 390 px shots of 2026-11-15 were the 500 px minimum; emulation found the real overflows (600eca2) | open |
| A4 | The shell here is bash 3.2: a command that mixes a heredoc with pipes or two heredocs is refused. Write a long commit message to a file and pass `-F <file>` | Several refused commits on 2026-11-15 | open |
