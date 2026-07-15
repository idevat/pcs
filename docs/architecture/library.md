# Library layer

Source: `pcs/lib/`

The library layer contains core business logic. Both CLI and daemon execute the
same library commands — the library is the single source of truth for cluster
operations.

## Library commands

Source: `pcs/lib/commands/`

Each library command is a function that receives `env: LibraryEnvironment` as
its first parameter and uses it to access services (CIB, report processor,
command runner, communication clients). Commands communicate results — errors,
warnings, informational messages — back to the caller through the report
processor. When a command encounters errors, it raises `LibraryError` to abort
execution. See [reports.md](reports.md) for details.

Command modules can be either single files or packages:

- **Single file** — e.g. `pcs/lib/commands/cib.py`, `pcs/lib/commands/node.py`
- **Package** — e.g. `pcs/lib/commands/constraint/` with `__init__.py` and
  submodules

When a module grows too large, it can be split into a package. The
`__init__.py` must re-export all public functions so that existing imports
(`from pcs.lib.commands import module_name`) continue to work.

When adding, removing, or renaming files within a package, `Makefile.am` must
be updated — it lists every `.py` file individually (not directories). Both
`pcs/Makefile.am` (source) and `pcs_test/Makefile.am` (tests) maintain such
file lists. See [overview.md — Makefile.am conventions](overview.md#makefileam-conventions)
for details.

## LibraryEnvironment

Source: `pcs/lib/env.py`

`LibraryEnvironment` is the dependency container for library commands. Commands
access infrastructure services through it:

- `env.logger` — logging
- `env.report_processor` — reporting (see [reports.md](reports.md))
- `env.cmd_runner()` — external command execution
- `env.get_cib()` / `env.push_cib()` — CIB access
- `env.get_corosync_conf()` — corosync configuration
- `env.get_known_hosts()` — host resolution for communication
- `env.get_node_communicator()` — HTTP communication with cluster nodes

Commands should rely on `env` to access services rather than importing and
constructing them directly.

### Design intent

`env` is a **dependency container** — it supplies services (communicator, report
processor, known hosts, command runner) but does not make business decisions.
Its methods should be predictable: return data, provide access to services,
and avoid side-effects like implicit reporting.

The **library command** owns business logic: it decides severity levels, how to
react to missing data, when to continue, and when to abort. This separation
keeps `env` reusable across commands with different error-handling strategies.

### Service propagation pattern

`LibraryEnvironment` propagates configuration (user identity, timeouts) to
communication layers automatically. When adding a new communication layer,
follow the established pattern:

```
LibraryEnvironment(user_login, user_groups, request_timeout)
  └── NodeCommunicatorFactory(user_login, user_groups, request_timeout)
        └── creates cookies: CIB_user, CIB_user_groups
```

Communication layers receive identity and timeout from `env`. New communication
code should obtain these values from `LibraryEnvironment`, not construct them
independently.

### Host resolution

`env` provides two host resolution methods:

- **`env.get_known_hosts()`** → `dict[str, PcsKnownHost]` — returns host
  records with addresses and ports.
- **`env.get_node_target_factory()`** → `NodeTargetLibFactory` →
  `RequestTarget` — for the `NodeCommunicator` pipeline. Includes built-in
  reporting (e.g. `HostNotFound` reports).

## Live-only vs. file-compatible commands

Commands that require a running cluster call `ensure_live_env(env)` (from
`pcs/lib/commands/cluster/utils.py`) which raises if CIB or corosync.conf
comes from a file. Commands that only modify CIB XML (without needing cluster
state, corosync.conf, or node communication) can work with both live and
file-based CIB.

### Conditionally using non-CIB data sources

`LibraryEnvironment` tracks live vs. file-based mode **independently** for
CIB and corosync.conf:

- `env.is_cib_live` — whether CIB comes from the live cluster (`True`) or
  from a file via the CLI's `-f` flag (`False`)
- `env.is_corosync_conf_live` — whether corosync.conf comes from the local
  file system (`True`) or was provided externally (`False`)

These are independent — a command using `-f` for CIB has `is_cib_live=False`
but `is_corosync_conf_live` can be `True` (if the user is on a cluster node)
or `False` (if corosync.conf data was provided separately).

Some commands support `-f` for CIB but can optionally benefit from reading
corosync.conf (e.g. to validate node names). In `-f` mode, the user may not
be on a cluster node, so corosync.conf may not be available. The pattern for
this is to gate the corosync access on `env.is_cib_live`:

```python
def my_command(env: LibraryEnvironment, ...) -> None:
    cib = env.get_cib()

    if env.is_cib_live:
        # Only read corosync.conf when working with live CIB.
        # In -f mode, the user may not be on a cluster node.
        corosync_conf = env.get_corosync_conf()
        # ... use corosync_conf for validation / warnings

    # ... modify cib
    env.push_cib()
```

Do not call `env.get_corosync_conf()` unconditionally in a command that
supports `-f` — it will attempt to read `/etc/corosync/corosync.conf` from
the local file system and raise `LibraryError` if the file doesn't exist.

### `_local` variants for corosync.conf file mode

A few commands support editing corosync.conf from a file via `--corosync_conf`.
These have a separate `_local` library command that takes corosync.conf content
as `bytes` and returns modified content — the CLI handler routes between live
and local variants based on whether `--corosync_conf` is specified.

Commands with `_local` variants: `setup_local`, `config_update_local`,
`generate_cluster_uuid_local`. The CLI uses `_corosync_conf_local_cmd_call()`
(`pcs/cluster.py`) to wrap file I/O around the local library command.

This is a **user-facing feature**, not a testing convenience. Most commands
that modify corosync.conf and distribute it to nodes (e.g. `add_nodes`,
`remove_nodes`, `update_link`, `rename`) do **not** have `_local` variants
— they inherently require live cluster coordination. Do not add `_local`
variants solely for testing purposes.

## CorosyncConfigFacade

Source: `pcs/lib/corosync/config_facade.py`

`env.get_corosync_conf()` returns a `CorosyncConfigFacade`. Commonly used
methods:

- `facade.get_nodes()` → `list[CorosyncNode]` — all defined nodes
- `facade.remove_nodes()` — remove nodes by name
- `facade.rename_node()` — rename a node
- `facade.add_nodes()` — add nodes to the configuration

`CorosyncNode` (`pcs/lib/corosync/node.py`) attributes:

- `name` (`Optional[str]`) — node name
- `addrs` (`Sequence[CorosyncNodeAddress]`) — node addresses
- `nodeid` (`Optional[str]`) — node ID

### Design: structural accessor, not validator

`CorosyncConfigFacade` is a **structural accessor** — it reads and modifies the
parsed config tree without enforcing consistency invariants (e.g. unique node
names, unique addresses, single `nodelist` section). Methods like
`remove_nodes()`, `rename_node()`, and `add_nodes()` iterate through **all**
matching sections and operate on every match.

This is by design. The corosync.conf parser (`config_parser.py`) faithfully
parses the config text into a tree structure without enforcing uniqueness —
multiple `nodelist` sections or multiple `node` subsections with the same name
are syntactically allowed.

**Validation happens at the command layer**, not in the facade:

- `config_validators.py` — `create()` and `add_nodes()` validators reject
  duplicate node names and addresses at creation time
- Library commands in `pcs/lib/commands/` perform their own consistency checks
  as needed

This means pcs guarantees consistency **at system boundaries** (cluster
creation, node addition) but does not re-validate at every modification
operation. If a user manually edits corosync.conf and introduces duplicates,
subsequent pcs operations will silently operate on all matching entries.

When writing new facade methods or library commands, follow this established
pattern: do not add validation that the rest of the system doesn't perform.
If existing operations (remove, update, rename) don't check for a particular
inconsistency, a new operation shouldn't either — consistency should come from
the facade's design, not from ad-hoc checks scattered across operations.

## Network communication

### Proxy handling

HTTP proxy environment variables (`https_proxy`, `all_proxy`) are **respected,
not disabled**. `pycurl` (NodeCommunicator) automatically uses them. This is
intentional — pcsd may legitimately need a proxy (e.g., webUI managing a remote
cluster over a corporate network).

When a connection fails, the established pattern is to **detect proxy and warn**:

```python
if is_proxy_set(os.environ):
    logger.warning("Proxy is set in environment variables, try disabling it")
```

This convention is consistent across all communication layers
(NodeCommunicator, `pcs/utils.py`, `pcsd/pcs.rb`).

### Request timeouts

Default timeout: `settings.default_request_timeout` (60 seconds). This applies
to individual HTTP requests, not to overall operations. APIv2 is designed for
long-running tasks — the polling loop has no timeout, but each poll request
does.
