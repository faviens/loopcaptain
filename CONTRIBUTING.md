# Contributing

Thank you for looking. A change moves the way [AGENTS.md §B](AGENTS.md#b-changing-this-repository)
says, for people and agents alike:

1. One branch, one logical change, a test that fails without it.
2. `make setup` once, then `make check` green: format, lint, types, tests,
   coverage. It is exactly what CI runs.
3. Commit subjects are `type(scope): subject`, the body says why. No AI
   attribution lines: the person who opens the pull request is the author.
4. A change to what a loop writes changes `standard/LOOPS.md`, the models
   and the schema together (`make schema`), and protocol 1 only grows.
5. Nothing names a company, a client or a real loop.

Not sure a change is wanted? Open an issue first: a bug, a loop that does
not show up, or a protocol proposal each have a form. Security problems go
privately, as [SECURITY.md](SECURITY.md) says.

## License

A contribution is taken under the [Apache License 2.0](LICENSE), like the
rest of the repository. There is no contributor agreement to sign.
