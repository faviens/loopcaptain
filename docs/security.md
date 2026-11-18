---
description: "What the board reads, runs and writes: how a browser gets in, how an answer reaches a loop signed, and what Start may run."
---

--8<-- "SECURITY.md:head"

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/entry-dark.svg">
  <img alt="How a browser gets into the board: loopcaptain serve prints an address with a new key; opening it sets a cookie made from the key and leads on to the page; every request after passes the host check, the cookie and, for a form, the token, and only the entry and the static files are open without the cookie." src="assets/entry-light.svg">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/steer-dark.svg">
  <img alt="How steering reaches a loop: an answer or a stop is appended to the loop's inbox.jsonl as a line signed with the inbox key, which the loop's helper checks before it acts; Start runs the loop's own commands.start without a shell, with a minimal environment that names the key's path, and keeps its records in the state folder." src="assets/steer-light.svg">
</picture>

--8<-- "SECURITY.md:model"
