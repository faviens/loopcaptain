# mcp_server/: the MCP door

Read [the root AGENTS.md](../../../AGENTS.md) first. `server.py` exposes
the protocol as MCP tools for a loop that an agent session drives without
a script. Run it with `loopcaptain mcp` (stdio).

Rules here:

1. Five tools and no more: `protocol`, `loop_register`, `emit`,
   `inbox_read`, `loop_status`. They mirror the helper's three verbs, so
   a loop reads the same on both doors and the tool list stays short in
   an agent's context. A new event is a new value for `emit`, not a tool.
2. A tool writes exactly what the helper in `standard/loops.py` would
   write. No tool adds state of its own; `tests/test_mcp.py` validates the
   folder the tools produce.
2. Every tool name that a loop needs is listed in section 5 of
   `standard/LOOPS.md`; a test compares the two.
3. Tool docstrings are the interface an agent reads: say what to pass and
   when to call, in the words of the standard.
4. A bad call is refused with one line that names the field. An event for
   a loop that is not registered is refused with the way out.
5. The server reads and writes only inside the `repo` it is given, by
   default the folder it was started in.
