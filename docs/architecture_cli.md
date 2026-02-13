# CLI layer

Source: `pcs/cli/`

The CLI layer handles command-line parsing, argument validation, and user
interaction. It translates user input into library command calls and presents
results back to the user. The CLI never contains business logic — it delegates
to the [library layer](architecture_library.md).

## Command pipeline

A CLI command flows through a fixed chain of registration points. Missing any
step causes runtime errors that are not caught by type checks or tests.

```
User input ("pcs cluster node clear ...")
  │
  ├─ 1. Routing         pcs/cli/routing/cluster.py      → selects handler
  │
  ├─ 2. CLI handler     pcs/cli/cluster/command.py      → parses args, calls lib
  │
  ├─ 3. lib_wrapper     pcs/cli/common/lib_wrapper.py   → exposes lib to CLI
  │
  └─ 4. Library command pcs/lib/commands/cluster.py     → business logic
```

The following registrations are also required when adding a new command but
don't affect the runtime call chain:

- **Daemon mapping** — `pcs/daemon/async_tasks/worker/command_mapping.py`
  (enables APIv2 execution)
- **Documentation** — help text and man page
- **Capability registration** — `pcsd/capabilities.xml.in`

### Routing

Source: `pcs/cli/routing/`

Each area has a routing module that maps CLI subcommand strings to handler
functions. `create_router()` builds a nested dispatch function from a dictionary
of `{subcommand: handler}` entries. Routers can be nested for multi-level
commands (e.g. `pcs cluster node clear`).

Entries within each router are in **alphabetical order**.

**Legacy routing:** Some older commands route through monolithic handler files
(`pcs/cluster.py`, `pcs/resource.py`, etc.) instead of the modular
`pcs/cli/<area>/command.py`. The routing files import from both — compare
`cluster_command.node_rename_cib` (new-style, from
`pcs/cli/cluster/command.py`) vs `cluster.config_update` (old-style, from
`pcs/cluster.py`). **New commands must use the modular style**
(`pcs/cli/<area>/command.py`).

### CLI handler

Source: `pcs/cli/<area>/command.py`

The handler function receives `(lib, argv, modifiers)` and:

1. Validates allowed flags: `modifiers.ensure_only_supported(...)`
2. Validates argument count (raises `CmdLineInputError()` on mismatch)
3. Calls the library command via `lib.<area>.<command>(...)`

### lib_wrapper

Source: `pcs/cli/common/lib_wrapper.py`

The `lib_wrapper` module connects CLI handler calls to library command
functions. Each area has a binding dictionary that maps string keys to library
command functions, wrapped with appropriate middleware.

**Forgetting the lib_wrapper entry** causes `AttributeError` at runtime — no
static check catches it.

**Important:** the area in lib_wrapper corresponds to the **library command
module** (`pcs/lib/commands/<area>.py`), not the CLI routing area. A command
routed through `pcs/cli/routing/cluster.py` may bind to `lib.cib.<command>` if
the library function lives in `pcs/lib/commands/cib.py`.

### Daemon command mapping

New library commands must be registered in `COMMAND_MAP`
(`pcs/daemon/async_tasks/worker/command_mapping.py`) to be available via APIv2.
See [architecture_daemon.md — Command mapping and permissions](architecture_daemon.md#command-mapping-and-permissions)
for details.

### Documentation

Both files must be updated:

- `pcs/usage.py` — CLI help text (shown by e.g. `pcs cluster --help`)
- `pcs/pcs.8.in` — man page (groff format). Hyphens in command names and flags
  must be escaped (`\-`), flags are bolded with `\fB...\fR`
  (e.g. `[\fB\-\-force\fR]`). Each entry starts with `.TP`.

### Capability registration

`pcsd/capabilities.xml.in` — daemon feature negotiation. Required for new
commands exposed via the daemon.

## Middleware

Source: `pcs/cli/common/middleware.py`, `pcs/cli/common/lib_wrapper.py`

The lib_wrapper binding specifies **middleware** that runs before and after the
library command. Middleware handles transparent file I/O for CIB and
corosync.conf:

```python
# Commands that read/write CIB (supports -f flag for local file)
middleware.build(middleware_factory.cib)

# Commands that read/write corosync.conf (supports --corosync_conf flag)
middleware.build(middleware_factory.corosync_conf_existing)

# Both CIB and corosync.conf
middleware.build(middleware_factory.cib, middleware_factory.corosync_conf_existing)

# No file middleware
middleware.build()
```

The CIB middleware handles the `-f` flag transparently: when the user passes
`-f <file>`, the middleware reads CIB from the file before the command runs
and writes it back after. The library command uses `env.get_cib()` /
`env.push_cib()` regardless — it doesn't know whether CIB comes from a live
cluster or a file. Any command bound with `middleware_factory.cib` automatically
supports the `-f` flag without explicit handling in the command.

The corosync.conf middleware works the same way for `--corosync_conf`.

See [architecture_library.md — Live-only vs. file-compatible commands](architecture_library.md#live-only-vs-file-compatible-commands)
for how the library layer interacts with this mechanism.

## Force flags pattern (CLI side)

Many commands support `--force` to override safety checks. The CLI handler
converts the modifier to a `force_flags` list and passes it to the library
command:

```python
def my_command(lib: Any, argv: Argv, modifiers: InputModifiers) -> None:
    modifiers.ensure_only_supported("-f", "--force")
    if len(argv) != 2:
        raise CmdLineInputError()
    force_flags = []
    if modifiers.get("--force"):
        force_flags.append(reports.codes.FORCE)
    lib.area.command(argv[0], argv[1], force_flags)
```

The library command declares `force_flags` as a parameter (typically with
default `()`) and uses it to decide whether to emit warnings (force applied)
or forceable errors (force not applied). See
[architecture_library.md — Forceable errors](architecture_library.md#forceable-errors-force-override-pattern)
for the library side of this pattern.

## Registration checklist (new command)

When adding a new CLI command, all of the following must be updated:

1. **Routing** (`pcs/cli/routing/<area>.py`) — add entry mapping CLI subcommand
   string to handler function (alphabetical order)
2. **CLI handler** (`pcs/cli/<area>/command.py`) — implement handler function
3. **lib_wrapper** (`pcs/cli/common/lib_wrapper.py`) — add binding entry
   (area corresponds to **library** module, not CLI routing area)
4. **Library command** (`pcs/lib/commands/<area>.py`) — implement business
   logic (see [architecture_library.md](architecture_library.md))
5. **Daemon command mapping**
   (`pcs/daemon/async_tasks/worker/command_mapping.py`) — add `COMMAND_MAP`
   entry with permission level (alphabetical order)
6. **Help text** (`pcs/usage.py`) and **man page** (`pcs/pcs.8.in`)
7. **Capability** (`pcsd/capabilities.xml.in`) — daemon feature negotiation
