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
execution. See [Reports](#reports) below for details.

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
file lists. See [architecture.md — Makefile.am conventions](architecture.md#makefileam-conventions)
for details.

## LibraryEnvironment

Source: `pcs/lib/env.py`

`LibraryEnvironment` is the dependency container for library commands. Commands
access infrastructure services through it:

- `env.logger` — logging
- `env.report_processor` — reporting (see [Reports](#reports) below)
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

## CIB-modifying commands

Commands that modify CIB follow this pattern:

```python
def my_command(env: LibraryEnvironment, ...) -> None:
    cib = env.get_cib()
    # validate, modify cib elements
    if env.report_processor.report_list(reports).has_errors:
        raise LibraryError()
    # perform modifications on cib
    env.push_cib()
```

For reference implementations, prefer recent code — older commands may use
outdated patterns. Good references:

| Function                  | Location                              | Demonstrates                              |
|---------------------------|---------------------------------------|-------------------------------------------|
| `element_description_set` | `pcs/lib/commands/cib.py`             | Simple CIB-modifying command              |
| `element_description_get` | `pcs/lib/commands/cib.py`             | Simple CIB-reading command                |
| `rename_node_cib`         | `pcs/lib/commands/cluster/node.py`    | Decomposition with `ReportItemList` helpers |
| `get_resource_ids`        | `pcs/lib/commands/remote_node.py`     | CIB-reading command                       |

### CIB section access

CIB XML has **mandatory** and **optional** sections (`pcs/lib/cib/sections.py`).
The helper functions in `pcs/lib/cib/tools.py` (e.g. `get_fencing_topology`,
`get_resources`, `get_constraints`) use `sections.get()` internally, which
behaves differently depending on section type:

- **Mandatory** (constraints, resources, nodes, crm_config, configuration):
  `sections.get()` finds the existing element or raises `LibraryError` if
  missing.
- **Optional** (fencing-topology, acls, alerts, tags, op_defaults,
  rsc_defaults): `sections.get()` **creates the element** if it doesn't exist.

This auto-creation is by design for commands that *write* to optional sections
— they can call e.g. `get_fencing_topology(cib)` and append elements without
checking existence first. But it's a trap for commands that only *read* an
optional section: calling `get_fencing_topology(cib)` in a read-only context
silently inserts an empty `<fencing-topology/>` into the CIB, which then gets
pushed as a modification.

When a command only needs to **iterate** over elements in an optional section
(without adding/removing), use direct XPath instead:

```python
# Read-only: iterate fencing levels without creating fencing-topology
for element in cib.findall(f".//{TAG_FENCING_LEVEL}"):
    ...

# Read-only: check whether an optional section exists and has content
acl_section = cib.find(".//acls")
if acl_section is not None and len(acl_section):
    ...

# Write: get-or-create the section, then modify
topology_el = get_fencing_topology(cib)
etree.SubElement(topology_el, TAG_FENCING_LEVEL, ...)
```

There is also `sections.exists(cib, sections.ACLS)` which checks for
existence without auto-creation, but direct `cib.find()` is simpler when you
also need to inspect the element's content.

Element tag constants are in `pcs/lib/cib/const.py`.

### `findall()` vs `xpath()`

lxml offers two query methods with different capabilities:

- **`findall()`** — uses **ElementPath** (a limited subset of XPath). Supports
  attribute predicates (`[@attr='value']`) and path navigation, but **not**
  XPath functions like `contains()`, `starts-with()`, `not()`, etc. Use this
  for straightforward structural queries.
- **`xpath()`** — uses **full XPath 1.0**. Supports all XPath functions and
  axes. Use when `findall()` is insufficient.

Most CIB queries in this codebase use `findall()`, which is sufficient for
attribute-based filtering. If you need XPath functions, switch to `xpath()`.

### `getparent()` type narrowing

lxml's `getparent()` returns `Optional[_Element]` because root elements have
no parent. When code uses `findall()` to locate nested elements, the parent
is guaranteed to exist structurally. Prefer `assert` over `cast` for this —
it provides a runtime check instead of silently hiding a potential error:

```python
# findall path includes the parent tag — parent is guaranteed to exist
for child_el in cib.findall(f".//{TAG_PARENT}/child[@attr='value']"):
    parent = child_el.getparent()
    assert parent is not None

# Avoid: silently assumes parent exists
parent = cast(_Element, element.getparent())
```

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

## CIB domain layer

Source: `pcs/lib/cib/`

The domain layer encapsulates structural knowledge about CIB (Cluster
Information Base) XML elements — how to find, create, validate, modify, and
convert them to DTOs.

### Organization

Modules are organized by CIB domain area:

| Module                         | Domain                                          |
|--------------------------------|-------------------------------------------------|
| `node.py`                      | Node elements (`<node uname="...">`)            |
| `fencing_topology.py`          | Fencing levels and topology                     |
| `constraint/`                  | Location, colocation, order, ticket constraints |
| `resource/`                    | Primitives, groups, clones, bundles, stonith    |
| `rule/`                        | Rule parsing, validation, evaluation            |
| `tag.py`, `alert.py`, `acl.py` | Other CIB sections                              |
| `tools.py`                     | Shared utilities (ID providers, element search) |
| `sections.py`                  | Section access (mandatory vs. optional)         |
| `const.py`                     | Element tag constants                           |

### Relationship to commands

The two layers have distinct responsibilities:

- **`pcs/lib/commands/`** — business logic: orchestrates operations, uses
  `LibraryEnvironment`, manages reporting, decides control flow (when to abort,
  when to warn, when to force)
- **`pcs/lib/cib/`** — CIB domain knowledge: reusable functions for querying
  and manipulating CIB elements, independent of `LibraryEnvironment`

The dependency direction is one-way: commands call cib, never the reverse.
Functions in `pcs/lib/cib/` do not use `LibraryEnvironment` or
`ReportProcessor` directly. When validation produces reports, cib functions
return `ReportItemList` for the caller to process.

### What belongs where

**Extract to `pcs/lib/cib/`** when code:
- Encapsulates non-trivial CIB structural knowledge (element creation with
  validation, complex queries, format-specific parsing)
- Has or will likely have multiple callers
- Can stand alone without `LibraryEnvironment` or reporting context

Good examples: `fencing_topology.add_level()` (validation + element creation),
`node.get_node_names()` (reusable query),
`constraint/location.create_plain_with_rule()` (complex element construction).

**Keep in `pcs/lib/commands/`** when code:
- Is simple XML manipulation (XPath query + attribute set) tightly coupled to
  a specific business operation and its reporting
- Has a single caller with no foreseeable reuse
- Would require passing `ReportProcessor` or creating a new return type just
  to separate it from the command

A simple XPath query in a command function is acceptable — not every line that
"knows about CIB structure" needs extraction.

### Legacy note

Not all existing code follows this ideal layering — some older command
functions contain CIB manipulation that could live in `pcs/lib/cib/` in a
clean design. If it works and has a single caller, there is no reason to move
it. Apply these principles when writing new code or when refactoring creates
a genuine readability or reuse benefit.

## Reports

Source: `pcs/common/reports/`

Reports are the primary mechanism for communicating outcomes (errors, warnings,
info) from library commands back to the caller.

### Key components

- **`ReportItem`** (`pcs/common/reports/item.py`) — domain object representing
  a single report with severity, message, and optional node context
- **`ReportItemDto`** (`pcs/common/reports/dto.py`) — serializable DTO for
  transport over APIv2
- **`ReportProcessor`** (`pcs/common/reports/processor.py`) — abstract
  processor; commands use `env.report_processor` to report items
- **`report_dto_to_item()`** (`pcs/common/reports/conversions.py`) — converts
  `ReportItemDto` back to `ReportItem`, optionally adding
  `ReportItemContext` (node provenance)

### Error signaling: LibraryError and reports

`LibraryError` (`pcs/lib/errors.py`) is a flow-control signal — it carries no
user-facing information itself. Commands report errors (and other severities)
via `env.report_processor` as they go, accumulating as much information as
possible (e.g. multiple validation errors) in a single run. When a command
reaches a state where continuing no longer makes sense due to previously
reported errors, it raises `LibraryError()` to abort. The typical pattern is:

```python
if env.report_processor.report_list(report_list).has_errors:
    raise LibraryError()
```

`ReportProcessor` tracks whether any error-severity report has been seen
(`has_errors` property). This allows commands to report multiple errors before
deciding to stop, giving users the most complete feedback possible.

**`ReportProcessor` is stateless beyond `has_errors`** — it does not store or
provide access to previously reported items. The `report()` and `report_list()`
methods dispatch each item immediately (to console, log, or in-memory buffer
depending on the subclass) but the base class retains only the error flag. When
a command needs to track whether specific actions occurred (e.g. "was any element
modified?"), use local state (booleans, counters) rather than querying the
report processor.

### Forceable errors (force override pattern)

Some validations should block command execution by default but allow the user
to override with CLI's `--force`. Without `--force` the report has ERROR
severity (with a `force_code` hint telling the user which flag overrides it);
with `--force` it becomes a WARNING and the command continues.

The command accepts a `force_flags` parameter and uses `get_severity()` to
decide between error and warning:

```python
from pcs.common import reports
from pcs.lib.errors import LibraryError

def my_command(
    env: LibraryEnvironment,
    ...,
    force_flags: reports.types.ForceFlags = (),
) -> None:
    report_processor = env.report_processor

    if something_suspicious:
        report_processor.report(
            reports.ReportItem(
                severity=reports.item.get_severity(
                    reports.codes.FORCE,
                    reports.codes.FORCE in force_flags,
                ),
                message=reports.messages.SomethingSuspicious(...),
            )
        )
        if report_processor.has_errors:
            raise LibraryError()
```

Key elements:
- **`force_flags: reports.types.ForceFlags = ()`** — collection of force codes;
  empty by default (no override)
- **`reports.item.get_severity(force_code, is_forced)`** — returns WARNING
  severity when `is_forced` is `True`, ERROR with `force_code` when `False`
- **`if report_processor.has_errors: raise LibraryError()`** — stops execution
  if the report was an error (i.e. user didn't use `--force`)

There is also `reports.item.get_severity_from_flags(force_code, force_flags)`
which combines the lookup — it checks whether `force_code` is in
`force_flags`. Use whichever reads better in context.

The forceable error pattern gives users maximum feedback before aborting.
A command may report multiple forceable errors before raising `LibraryError()`
— the user sees all issues at once, not one at a time.

See [architecture_cli.md](architecture_cli.md) for how the CLI propagates
`--force` to library commands.

### Report message catalog

Report messages are defined in `pcs/common/reports/messages.py` — each is a
frozen dataclass inheriting from `ReportItemMessage`, with a corresponding code
in `pcs/common/reports/codes.py`.

The catalog is large and organized by domain area. Before creating a new message
type, search existing messages for a semantic match. Many common situations
(node communication failures, invalid input, missing configuration) already have
established messages with consistent wording and structure.

#### Adding a new report message

Three files must be updated (an `AllClassesTested` meta-test enforces the test):

1. **`pcs/common/reports/codes.py`** — add code constant (alphabetical order)
2. **`pcs/common/reports/messages.py`** — add `@dataclass(frozen=True)` class
   inheriting `ReportItemMessage`, grouped with related messages
3. **`pcs_test/tier0/common/reports/test_messages.py`** — add test class with
   the **same name** as the message class, inheriting `NameBuildTest`

### Forwarding remote reports

When a command receives reports from a remote node (e.g. via APIv2), the
established pattern is:

```python
context = reports.ReportItemContext(node_label)
report_list = [
    reports.report_dto_to_item(report, context)
    for report in remote_reports
]
env.report_processor.report_list(report_list)
```

Examples: `pcs/lib/communication/scsi.py`,
`pcs/lib/communication/cluster.py`,
`pcs/lib/communication/pcs_cfgsync.py`.

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
