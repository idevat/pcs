# Architecture

## Overall Structure

PCS consists of several components:

### Core Components

1. **CLI** (`pcs/pcs`)
   - Command-line interface for cluster management
   - Entry point: `pcs/entry_points/`
   - Command implementations: `pcs/cli/`

2. **Library** (`pcs/lib/`)
   - Core business logic
   - Commands: `pcs/lib/commands/` (invoked by both CLI and daemon)
   - Shared utilities: `pcs/common/`

3. **Daemon - pcsd** (HTTP server for remote management)
   - **Tornado daemon** (Python) - `pcs/daemon/`
     - Main implementation, actively developed
     - Entry point: `pcs/daemon/run.py`
     - Default port: 2224
   - **Ruby daemon** (legacy) - `pcsd/`
     - Original Sinatra-based implementation
     - Still runs alongside Tornado for endpoints not yet migrated
     - Being phased out

### Optional Components

4. **Web UI** (optional, separate project)
   - Not part of pcs sources
   - Separate repository: [pcs-web-ui](https://github.com/ClusterLabs/pcs-web-ui)
   - Can run as Cockpit plugin or standalone app served by pcsd
   - Enabled via `--enable-webui` configure flag
   - pcsd provides backend API support when enabled

5. **SNMP Agent** (`pcs/snmp/`)
   - Optional SNMP monitoring support
   - Binary: `pcs_snmp_agent`
   - AgentX-based SNMP subagent

## pcsd Daemon

### Overview

- **Framework**: Tornado
- **Default port**: 2224
- **Entry point**: `pcs/daemon/run.py`

The daemon handles HTTP requests for cluster operations, enabling remote
management and async task processing.

### Routing

Routes are configured in `pcs/daemon/run.py`. The daemon serves multiple purposes:
- APIv2 endpoints (async task processing)
- Legacy sync endpoints
- Web UI (if applicable)

### API Layers (Python)

The Python daemon has multiple API handler layers, reflecting the project's
evolution:

- **APIv0** (`pcs/daemon/app/api_v0.py`) — Oldest Python API layer, legacy
- **APIv1** (`pcs/daemon/app/api_v1.py`) — Improved interface, legacy
- **APIv2** (`pcs/daemon/app/api_v2.py`) — Current target architecture, async
  task processing

All three share the same backend: they create `CommandDto` and submit tasks to
the async scheduler. The difference is in their HTTP interface and client
compatibility. **New development targets APIv2.**

### Ruby Legacy Daemon

For historical reasons (original implementation was Ruby), a second daemon runs
alongside the Tornado daemon. The Tornado daemon delegates requests to the Ruby
daemon when there's no Python implementation yet.

**This is legacy** - new features should be implemented in Python, not Ruby.

## APIv2

APIv2 enables asynchronous HTTP request processing.

### Handler

Main handler: `pcs/daemon/app/api_v2.py`

### Endpoints

- **`task/create`** - Submit a request, get task ID immediately
- **`task/result`** - Check task status and get results (returns `ReportItem` list)
- **`task/kill`** - Terminate a running task
- **`task/run`** - Synchronous execution (`task/create` + polling `task/result`)

### Flow

1. Client calls `task/create` with request
2. Server creates task ID and queues request
3. Server returns task ID immediately (non-blocking)
4. Request is processed asynchronously by a library command from
   `pcs/lib/commands/`
5. Client polls `task/result` with task ID to get status and `ReportItem` list
6. When complete, results are returned

### Data Layer (DTOs, Types, Serialization)

APIv2 communication uses typed data structures defined in `pcs/common/`:

- **DTOs**: `pcs/common/async_tasks/dto.py` — dataclasses representing API
  payloads and responses (`CommandDto`, `TaskIdentDto`, `TaskResultDto`, etc.)
- **Types/Enums**: `pcs/common/async_tasks/types.py` — enums for task-related
  values (`TaskFinishType`, `TaskState`, `TaskKillReason`). These use
  `AutoNameEnum` (from `pcs/common/types.py`), where the enum value equals its
  name (e.g. `TaskFinishType.SUCCESS` has value `"SUCCESS"`)
- **Serialization**: `pcs/common/interface/dto.py` — `to_dict()` converts a DTO
  to a JSON-serializable dict, `from_dict()` deserializes a dict back to a typed
  DTO (handles enum casting, nested dataclasses, etc.)

When writing code that produces or consumes APIv2 payloads, use these DTOs and
enums rather than raw dicts and string literals — they provide type safety and a
single source of truth for the API contract.

#### Domain Objects vs DTOs

The codebase distinguishes between **domain objects** and **DTOs** (Data Transfer
Objects). Both are dataclasses, but they serve different purposes and have
different base classes (`pcs/common/interface/dto.py`):

- **Domain objects** (e.g. `ReportItem`, `ReportItemMessage` subclasses) — rich
  objects with business logic, properties, and class hierarchies. Inherit from
  `ImplementsToDto`.
- **DTOs** (e.g. `ReportItemDto`, `CommandDto`, `TaskResultDto`) — flat,
  serializable structures for API transport. Inherit from `DataTransferObject`.

The conversion pipeline is always two steps:

```
Domain object  →  .to_dto()  →  DTO  →  to_dict()  →  dict
dict  →  from_dict(DtoClass, d)  →  DTO  →  .from_dto()  →  Domain object
```

**`to_dict()` only works correctly on `DataTransferObject` instances.** Internally
it uses `dataclasses.fields()` on the *static* type annotations to traverse
fields. This means it cannot handle polymorphic domain objects — for example,
calling `to_dict()` on a `ReportItem` silently loses the `message` content,
because the annotated type `ReportItemMessage` has no dataclass fields even though
the actual runtime instance is a concrete subclass with data. Always convert
domain objects to DTOs first via `.to_dto()`.

### Response Structure

`TaskResultDto` is a complete record of a task. It includes the original
command, accumulated reports, execution state, and result:

```
TaskResultDto
├── task_ident: str
├── command: CommandDto              # full original request
│   ├── command_name: str
│   ├── params: Dict[str, Any]
│   └── options: CommandOptionsDto   # includes effective_username, etc.
├── reports: List[ReportItemDto]
├── state: TaskState
├── task_finish_type: TaskFinishType
├── kill_reason: Optional[TaskKillReason]
└── result: Any
```

The `command` field echoes back the entire original `CommandDto` including
`options`. This is by design — it provides a complete audit trail and enables
clients to correlate responses with requests. Both `task/result` and `task/run`
return this structure.

### Task Result Behavior

Each call to `task/result` returns **all accumulated reports** since task
creation — the report list is append-only and never cleared. Clients that poll
`task/result` repeatedly will receive growing lists. To identify new reports,
track the number of already-seen reports and slice from that index.

### Task Lifecycle Invariants

`task/create` is an **irreversible operation**. Once the server returns a task
ID, the task is queued for execution and will run regardless of whether the
client polls `task/result`. There is no "undo" — only `task/kill` can attempt
to stop a running task, and even that may arrive after execution completes.

Implications for code that creates tasks on remote nodes:

- A successful `task/create` followed by a failed `task/result` poll does **not**
  mean the task didn't execute — it means you lost visibility, not control
- Retry or failover logic that creates the same task on another node risks
  concurrent execution of the same operation
- Code that creates tasks on remote nodes must treat a successful `task/create`
  as a commitment to that node

### Library Commands

Task processing is delegated to library commands in `pcs/lib/commands/`. These
contain the core business logic.

Command mapping: `pcs/daemon/async_tasks/worker/command_mapping.py`

### Command Permissions

Each command in `command_mapping.py` has a `required_permission` that the daemon
checks before execution. Permission levels
(`pcs/common/permissions/types.py`):

- **`UNRESTRICTED`** — No authorization check. Used for commands that delegate
  authorization to another layer (e.g., a dispatcher forwarding to a remote
  node, where the remote node enforces its own permissions for the actual
  command).
- **`READ`** — Read-only operations
- **`WRITE`** — Modifying operations (implies READ)
- **`GRANT`** — Permission management operations
- **`FULL`** — Administrative operations (implies READ + WRITE + GRANT)
- **`SUPERUSER`** — Reserved for `hacluster` (implies all)

Permission is enforced on the local node before the command runs. For commands
that forward operations to remote nodes, the remote node performs its own
independent permission check for the forwarded command.

## Library Environment

`LibraryEnvironment` (`pcs/lib/env.py`) is the service provider for library
commands. Commands receive it as their first parameter (`env`) and obtain
everything they need from it:

- `env.logger` — logging
- `env.report_processor` — reporting (see Reports below)
- `env.api_v2_client` — APIv2 client for remote communication
- `env.get_known_hosts()` — host resolution

Commands should rely on `env` to access services rather than importing and
constructing them directly.

### Service Propagation Pattern

`LibraryEnvironment` propagates configuration (user identity, timeouts) to
communication layers automatically. When adding a new communication layer,
follow the established pattern:

```
LibraryEnvironment(user_login, user_groups, request_timeout)
  ├── NodeCommunicatorFactory(user_login, user_groups, request_timeout)
  │     └── creates cookies: CIB_user, CIB_user_groups
  └── ApiV2Client(user_login, user_groups, request_timeout)
        └── injects into payload: options.effective_username, options.effective_groups
```

Both communication layers receive the same identity and timeout from `env`.
The mechanism differs (cookies vs. JSON payload fields), but the source of
truth is the same. New communication code should obtain these values from
`LibraryEnvironment`, not construct them independently.

### Host Resolution

`env` provides two host resolution methods, each tied to a different
communication pipeline:

- **`env.get_known_hosts()`** → `Dict[str, PcsKnownHost]` — for the APIv2
  pipeline. Returns host records with addresses and ports. Used with
  `ApiV2Client` for direct HTTP communication.
- **`env.get_node_target_factory()`** → `NodeTargetLibFactory` → `RequestTarget`
  — for the legacy `NodeCommunicator` pipeline. Includes built-in reporting
  (e.g. `HostNotFound` reports), but is coupled to the legacy communication
  layer.

New code should use `get_known_hosts()` + `ApiV2Client`. `NodeTargetLibFactory`
should not be used in new APIv2 commands — its built-in reporting side-effects
don't fit the APIv2 model where the command controls its own error handling.
For APIv2 commands, host resolution logic (including what to do when a host is
not found) is the command's responsibility.

### Design Intent

`env` is a **service provider** — it supplies services (communicator, report
processor, known hosts, command runner) but does not make business decisions.
Its methods should be predictable: return data, provide access to services,
and avoid side-effects like implicit reporting.

The **library command** owns business logic: it decides severity levels, how to
react to missing data, when to continue, and when to abort. This separation
keeps `env` reusable across commands with different error-handling strategies.

## Authentication & User Identity

### Impersonation Model

pcsd-to-pcsd communication authenticates via **token** (shared secret between
nodes). The token resolves to the `hacluster` superuser. The actual user
identity (the person using CLI or webUI) is forwarded separately:

- **Legacy (NodeCommunicator):** `CIB_user` and `CIB_user_groups` cookies
- **APIv2:** `CommandOptionsDto.effective_username` and `.effective_groups`
  fields in the JSON payload

On the receiving side, the executor (`pcs/daemon/async_tasks/worker/executor.py`)
resolves the effective user: if the authenticated user is a superuser and
`effective_username` is provided, the command runs under the effective identity.
Otherwise, it runs as the authenticated user.

### Where Identity Is Used

`LibraryEnvironment` receives the resolved identity as `user_login` and
`user_groups`. These are used for:

- **CommandRunner** (`env.cmd_runner()`) — sets `CIB_user` environment variable
  for Pacemaker commands
- **NodeCommunicatorFactory** — creates `CIB_user`/`CIB_user_groups` cookies
  for legacy remote requests
- **ApiV2Client** — injects `effective_username`/`effective_groups` into
  forwarded command payloads

## Reports

Reports are the primary mechanism for communicating outcomes (errors, warnings,
info) from library commands back to the caller.

### Key Components

- **`ReportItem`** (`pcs/common/reports/item.py`) — domain object representing a
  single report with severity, message, and optional node context
- **`ReportItemDto`** (`pcs/common/reports/dto.py`) — serializable DTO for
  transport over APIv2
- **`ReportProcessor`** (`pcs/common/reports/processor.py`) — abstract
  processor; commands use `env.report_processor` to report items
- **`report_dto_to_item()`** (`pcs/common/reports/conversions.py`) — converts
  `ReportItemDto` back to `ReportItem`, optionally adding `ReportItemContext`
  (node provenance)

### Error Signaling: LibraryError and Reports

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

### Forceable Errors (Force Override Pattern)

Some validations should block command execution by default but allow the user
to override with `--force`. This is the "forceable error" pattern — without
`--force` the report has ERROR severity (with a `force_code` hint telling the
user which flag overrides it); with `--force` it becomes a WARNING and the
command continues.

#### Library command side

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

    # Validation that can be overridden
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

    # ... proceed with the actual operation
```

Key elements:
- **`force_flags: reports.types.ForceFlags = ()`** — collection of force codes;
  empty by default (no override)
- **`reports.item.get_severity(force_code, is_forced)`** — returns WARNING
  severity when `is_forced` is True, ERROR with `force_code` when False
- **`if report_processor.has_errors: raise LibraryError()`** — stops execution
  if the report was an error (i.e. user didn't use `--force`)

There is also `reports.item.get_severity_from_flags(force_code, force_flags)`
which combines the lookup — it checks whether `force_code` is in
`force_flags`. Use whichever reads better in context.

#### CLI handler side

The CLI propagates `--force` to the library command:

```python
def my_cli_command(lib, argv, modifiers):
    modifiers.ensure_only_supported("--force", "-f")
    lib.area.my_command(..., force_flags=modifiers.get_force_flags())
```

Or for commands with a simple boolean flag (older pattern):

```python
lib.area.my_command(..., allow_something=modifiers.get("--force"))
```

#### Design intent

The forceable error pattern gives users maximum feedback before aborting.
A command may report multiple forceable errors before raising `LibraryError()`
— the user sees all issues at once, not one at a time. This is especially
valuable for commands that perform multiple validations.

### Report Message Catalog

Report messages are defined in `pcs/common/reports/messages.py` — each is a
frozen dataclass inheriting from `ReportItemMessage`, with a corresponding code
in `pcs/common/reports/codes.py`.

The catalog is large and organized by domain area. Before creating a new message
type, search existing messages for a semantic match. Many common situations
(node communication failures, invalid input, missing configuration) already have
established messages with consistent wording and structure.

#### Adding a New Report Message

Three files must be updated (an `AllClassesTested` meta-test enforces the test):

1. **`pcs/common/reports/codes.py`** — add code constant (alphabetical order)
2. **`pcs/common/reports/messages.py`** — add `@dataclass(frozen=True)` class
   inheriting `ReportItemMessage`, grouped with related messages
3. **`pcs_test/tier0/common/reports/test_messages.py`** — add test class with
   the **same name** as the message class, inheriting `NameBuildTest`

### Forwarding Remote Reports

When a command receives reports from a remote node (e.g. via APIv2), the
established pattern is:

```python
context = reports.ReportItemContext(node_label)
report_list = [reports.report_dto_to_item(report, context) for report in remote_reports]
env.report_processor.report_list(report_list)
```

Examples: `pcs/lib/communication/scsi.py`, `pcs/lib/communication/cluster.py`,
`pcs/lib/communication/pcs_cfgsync.py`.

## Network Communication Conventions

### Proxy Handling

HTTP proxy environment variables (`https_proxy`, `all_proxy`) are **respected,
not disabled**. Both `pycurl` (NodeCommunicator) and `urllib` (ApiV2Client)
automatically use them. This is intentional — pcsd may legitimately need a proxy
(e.g., webUI managing a remote cluster over a corporate network).

When a connection fails, the established pattern is to **detect proxy and warn**:

```python
if is_proxy_set(os.environ):
    logger.warning("Proxy is set in environment variables, try disabling it")
```

This convention is consistent across all communication layers (NodeCommunicator,
`pcs/utils.py`, `pcsd/pcs.rb`). See https://bugzilla.redhat.com/show_bug.cgi?id=1315627
for the history and rationale.

### Request Timeouts

Default timeout: `settings.default_request_timeout` (60 seconds). This applies
to individual HTTP requests, not to overall operations. APIv2 is designed for
long-running tasks — the polling loop has no timeout, but each poll request does.

## CLI Command Pipeline

A CLI command flows through a fixed chain of registration points. Missing any
step causes runtime errors that are not caught by type checks or tests.

### Call Chain

```
User input ("pcs cluster node clear ...")
  ↓
1. Routing         pcs/cli/routing/cluster.py        → selects handler function
  ↓
2. CLI handler     pcs/cli/cluster/command.py         → parses args, calls lib
  ↓
3. lib_wrapper     pcs/cli/common/lib_wrapper.py      → exposes lib to CLI
  ↓
4. Library command pcs/lib/commands/cluster.py         → business logic
  ↓
5. Daemon mapping  pcs/daemon/async_tasks/worker/      → enables APIv2 execution
                   command_mapping.py
```

Documentation (help text, man page) and capability registration are also
required but don't affect the runtime call chain.

**Legacy routing:** Some older commands route through monolithic handler files
(`pcs/cluster.py`, `pcs/resource.py`, etc.) instead of the modular
`pcs/cli/<area>/command.py`. The routing files (`pcs/cli/routing/`) import from
both — compare `cluster_command.node_rename_cib` (new-style, from
`pcs/cli/cluster/command.py`) vs `cluster.config_update` (old-style, from
`pcs/cluster.py`). **New commands should use the modular style**
(`pcs/cli/<area>/command.py`).

### Registration Checklist (New Command)

1. **Routing** (`pcs/cli/routing/<area>.py`) — add entry mapping CLI subcommand
   string to handler function. Entries are in alphabetical order within each
   router.
2. **CLI handler** (`pcs/cli/<area>/command.py`) — implement handler function.
   Pattern:
   - `modifiers.ensure_only_supported(...)` to validate allowed flags
   - Argument count validation (`if len(argv) != N: raise CmdLineInputError()`)
   - Call library command via `lib.<area>.<command>(...)`
   - For commands supporting `--force`: convert modifier to `force_flags` list
     and pass to library command (see "Force Flags Pattern" below)
3. **lib_wrapper** (`pcs/cli/common/lib_wrapper.py`) — add entry to the area's
   binding dictionary. This maps string keys to library command functions.
   **Forgetting this step** causes `AttributeError` at runtime — no static
   check catches it. **Important:** the area in lib_wrapper corresponds to the
   **library command module** (`pcs/lib/commands/<area>.py`), not the CLI
   routing area. A command routed through `pcs/cli/routing/cluster.py` may bind
   to `lib.cib.<command>` if the library function lives in
   `pcs/lib/commands/cib.py`.
4. **Library command** (`pcs/lib/commands/<area>.py`) — implement business
   logic. See "Library Commands" section below.
5. **Daemon command mapping**
   (`pcs/daemon/async_tasks/worker/command_mapping.py`) — add entry to
   `COMMAND_MAP` with appropriate permission level. Entries in alphabetical
   order. The key format is `"<area>.<function>"` where `<area>` matches the
   lib_wrapper area and `<function>` matches the lib_wrapper binding key.
6. **Documentation** — both files must be updated:
   - `pcs/usage.py` — CLI help text (shown by `pcs cluster --help`)
   - `pcs/pcs.8.in` — man page (groff format). Hyphens in command names and
     flags must be escaped (`\-`), flags are bolded with `\fB...\fR`
     (e.g. `[\fB\-\-force\fR]`). Each entry starts with `.TP`.
7. **Capability** — `pcsd/capabilities.xml.in` for daemon feature negotiation.

### Middleware

The `lib_wrapper.py` binding specifies **middleware** that runs before the
library command:

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
`-f <file>`, the middleware reads CIB from the file before the command runs,
and writes it back after. The library command uses `env.get_cib()` /
`env.push_cib()` regardless — it doesn't know whether CIB comes from a live
cluster or a file. This means any command bound with `middleware_factory.cib`
automatically supports the `-f` flag without explicit handling.

### Force Flags Pattern

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
or forceable errors (force not applied). See the Reports section for details
on forceable errors.

## Library Commands

Library commands (`pcs/lib/commands/`) contain core business logic. They are
the single source of truth for cluster operations — both CLI and daemon
execute the same library commands.

### Structure

Each library command receives `env: LibraryEnvironment` as its first parameter
and uses it to access services (CIB, corosync.conf, report processor, command
runner, communication clients).

### Organization

Command modules in `pcs/lib/commands/` can be either single files or packages:

- **Single file** — e.g. `pcs/lib/commands/cib.py`, `pcs/lib/commands/node.py`
- **Package** — e.g. `pcs/lib/commands/constraint/` with `__init__.py` and
  submodules

When a module grows too large, it can be split into a package. The
`__init__.py` must re-export all public functions so that existing imports
(`from pcs.lib.commands import module_name`) continue to work.

When adding, removing, or renaming files within a package, `Makefile.am`
must be updated — it lists every `.py` file individually (not directories).
Both `pcs/Makefile.am` (source) and `pcs_test/Makefile.am` (tests) maintain
such file lists. See the "Build System" section for details on source vs.
generated files.

### CIB-Modifying Command Pattern

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
outdated patterns. Good references for CIB-modifying commands:

| Function                  | Location                          | Demonstrates                     |
|---------------------------|-----------------------------------|----------------------------------|
| `element_description_set` | `pcs/lib/commands/cib.py`         | Simple CIB-modifying command     |
| `element_description_get` | `pcs/lib/commands/cib.py`         | Simple CIB-reading command       |
| `rename_node`             | `pcs/lib/commands/cib.py`         | Decomposition with `ReportItemList` helpers |
| `get_resource_ids`        | `pcs/lib/commands/remote_node.py` | CIB-reading command              |

### CIB Section Access

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
optional section: calling `get_fencing_topology(cib)` in a command that may
not write to it silently inserts an empty `<fencing-topology/>` into the CIB,
which then gets pushed as a modification.

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

#### `findall()` vs `xpath()`

lxml offers two query methods with different capabilities:

- **`findall()`** — uses **ElementPath** (a limited subset of XPath). Supports
  attribute predicates (`[@attr='value']`) and path navigation, but **not**
  XPath functions like `contains()`, `starts-with()`, `not()`, etc. Use this
  for straightforward structural queries.
- **`xpath()`** — uses **full XPath 1.0**. Supports all XPath functions and
  axes. Use when `findall()` is insufficient.

Most CIB queries in this codebase use `findall()`, which is sufficient for
attribute-based filtering. If you need XPath functions, switch to `xpath()`.

#### `getparent()` type narrowing

lxml's `getparent()` returns `Optional[_Element]` because root elements have
no parent. When code uses `findall()` to locate nested elements, the parent
is guaranteed to exist structurally. Prefer `assert` over `cast` for this —
it provides a runtime check instead of silently hiding a potential error:

```python
# Preferred: runtime check of structural invariant
parent = element.getparent()
assert parent is not None

# Avoid: silently assumes parent exists
parent = cast(_Element, element.getparent())
```

### Live-Only vs. File-Compatible Commands

Commands that require a running cluster call `ensure_live_env(env)` (from
`pcs/lib/commands/cluster/common.py`) which raises if CIB or corosync.conf
comes from a file. Commands that only modify CIB XML (without needing cluster
state, corosync.conf, or node communication) can work with both live and
file-based CIB.

#### `_local` Variants for Corosync.conf File Mode

A few commands support editing corosync.conf from a file via `--corosync_conf`.
These have a separate `_local` library command that takes corosync.conf content
as `bytes` and returns modified content — the CLI handler routes between live
and local variants based on whether `--corosync_conf` is specified.

Commands with `_local` variants: `setup_local`, `config_update_local`,
`generate_cluster_uuid_local`. The CLI uses `_corosync_conf_local_cmd_call()`
(`pcs/cluster.py`) to wrap file I/O around the local library command.

**This is a user-facing feature**, not a testing convenience. Most commands
that modify corosync.conf and distribute it to nodes (e.g. `add_nodes`,
`remove_nodes`, `update_link`, `rename`) do **not** have `_local` variants
— they inherently require live cluster coordination. Do not add `_local`
variants solely for testing purposes.

### Conditionally Using Non-CIB Data Sources

`LibraryEnvironment` tracks live vs. file-based mode **independently** for
CIB and corosync.conf:

- `env.is_cib_live` — whether CIB comes from the live cluster (True) or
  from a file via `-f` (False)
- `env.is_corosync_conf_live` — whether corosync.conf comes from the local
  file system (True) or was provided externally (False)

These are independent — a command using `-f` for CIB has `is_cib_live=False`
but `is_corosync_conf_live` can be True (if the user is on a cluster node)
or False (if corosync.conf data was provided separately).

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

### CorosyncConfigFacade

`env.get_corosync_conf()` returns a `CorosyncConfigFacade`
(`pcs/lib/corosync/config_facade.py`). Commonly used methods:

- `facade.get_nodes()` → `list[CorosyncNode]` — all defined nodes
- `CorosyncNode.name` (`Optional[str]`) — node name
- `CorosyncNode.addrs` — node addresses
- `CorosyncNode.nodeid` (`Optional[str]`) — node ID

#### Design: Structural Accessor, Not Validator

`ConfigFacade` is a **structural accessor** — it reads and modifies the parsed
config tree without enforcing consistency invariants (e.g. unique node names,
unique addresses, single `nodelist` section). Methods like `remove_nodes()`,
`rename_node()`, and `add_nodes()` iterate through **all** matching sections
and operate on every match.

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
subsequent pcs operations will silently operate on all matching entries — the
same way `remove_nodes()`, `update_link()`, and other facade methods do.

When writing new facade methods or library commands, follow this established
pattern: **do not add validation that the rest of the system doesn't perform**.
If existing operations (remove, update, rename) don't check for a particular
inconsistency, a new operation shouldn't either — consistency should come from
the facade's design, not from ad-hoc checks scattered across operations.

## CIB Domain Layer

`pcs/lib/cib/` is the domain layer for CIB (Cluster Information Base) XML. It
encapsulates structural knowledge about CIB elements — how to find, create,
validate, modify, and convert them to DTOs.

### Organization

Modules are organized by CIB domain area:

- `node.py` — node elements (`<node uname="...">`)
- `fencing_topology.py` — fencing levels and topology
- `constraint/` — location, colocation, order, ticket constraints
- `resource/` — primitives, groups, clones, bundles, stonith, remote/guest nodes
- `rule/` — rule parsing, validation, evaluation, CIB conversion
- `tag.py`, `alert.py`, `acl.py` — other CIB sections
- `tools.py` — shared utilities (ID providers, element search, multivalue attrs)
- `sections.py` — CIB section access (mandatory vs. optional)
- `const.py` — element tag constants

### Relationship to `pcs/lib/commands/`

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

### What Belongs Where

**Extract to `pcs/lib/cib/`** when code:
- Encapsulates non-trivial CIB structural knowledge (element creation with
  validation, complex queries, format-specific parsing)
- Has or will likely have multiple callers
- Can stand alone without `LibraryEnvironment` or reporting context

Good examples: `fencing_topology.add_level()` (validation + element creation),
`node.get_node_names()` (reusable query), `constraint/location.create_plain_with_rule()`
(complex element construction).

**Keep in `pcs/lib/commands/`** when code:
- Is simple XML manipulation (XPath query + attribute set) tightly coupled to
  a specific business operation and its reporting
- Has a single caller with no foreseeable reuse
- Would require passing `ReportProcessor` or creating a new return type just
  to separate it from the command

A simple XPath query in a command function is acceptable — not every line that
"knows about CIB structure" needs extraction. Apply the "Readability Through
Simplicity" test from `docs/development-principles.md`: extract when the
extracted code is noise that obscures the main logic; don't extract when the
reader needs to read both places to understand either one.

### Legacy Note

Not all existing code follows this ideal layering — some older command
functions contain CIB manipulation that could live in `pcs/lib/cib/` in a
clean design. If it works and has a single caller, there is no reason to move
it. Apply these principles when writing new code or when refactoring creates
a genuine readability or reuse benefit.

## Key Directories

- `pcs/` - CLI entry point
- `pcs/lib/` - Core library (business logic)
- `pcs/lib/commands/` - Library commands (invoked by daemon)
- `pcs/daemon/` - pcsd daemon (Tornado server)
- `pcs/daemon/app/` - HTTP handlers
- `pcs/daemon/async_tasks/` - Async task processing
- `pcsd/` - Ruby legacy daemon code

## Build System

The project uses GNU Autotools for its build system.

### Workflow

```
autogen.sh          →  configure  →  make
(autoreconf -i -v)     (from .ac)    (from Makefile.am)
```

1. `autogen.sh` runs `autoreconf` to generate the `configure` script from
   `configure.ac`
2. `./configure` checks dependencies and generates `Makefile` (and other files)
   from `*.in` templates
3. `make` builds, installs dependencies, and runs targets

### Source vs. Generated Files

When modifying the build system, edit the **source** files — never the generated
ones:

| Edit these (source)        | Don't edit (generated)                         |
|----------------------------|-------------------------------------------------|
| `configure.ac`             | `configure`, `config.status`, `config.log`      |
| `Makefile.am`              | `Makefile`, `Makefile.in`                        |
| `*.in` templates           | Their output files (without `.in` suffix)        |
| `m4/*.m4` (custom macros)  | `aclocal.m4`, `autom4te.cache/`                  |

Generated files are listed in `.gitignore`. After editing any `.in` file or
`configure.ac`, re-run `./configure` (or `make` will do it automatically if
timestamps trigger autotools re-generation).

### Makefile.am Conventions

- **`EXTRA_DIST`** — files included in distribution tarballs (`make dist`).
  All distributed files must be listed here (except autotools-generated ones).
- **`MAINTAINERCLEANFILES`** — generated files removed by
  `make maintainer-clean`. When a new generated file appears in the tree,
  add it here.
- Entries in list variables (`EXTRA_DIST`, `MAINTAINERCLEANFILES`, etc.) are
  kept in **alphabetical order**.

### .gitignore and Tool Integration

Generated and temporary files are listed in `.gitignore`. Tools like `typos`
and `ruff` respect `.gitignore` by default, so adding a file to `.gitignore`
automatically excludes it from quality checks as well.

## Quality Checks

`make check` runs the full quality-check pipeline, defined as the `check-local`
target in `Makefile.am`:

```
typos_check → ruff_lint → ruff_isort_check → ruff_format_check → mypy
  → tests_tier0 → tests_tier1 → pcsd-tests
```

Individual checks can be run separately (e.g. `make typos_check`, `make mypy`).

### Tool Configuration

| Tool    | Config file(s)                     | Notes                               |
|---------|------------------------------------|--------------------------------------|
| `typos` | `typos.toml`, `typos_known`        | Baseline-diff approach (see below)   |
| `ruff`  | `pyproject.toml`                   | Linting, import sorting, formatting  |
| `mypy`  | `mypy.ini`                         | Static type checking                 |

### Typos Checker

The typos checker uses a **baseline-diff** approach:

1. `typos` scans the tree and produces a sorted list of findings
2. The list is compared against `typos_known` (committed baseline)
3. If they differ, the check fails

This means:
- **New typos** cause failure (they appear in output but not in baseline)
- **Fixed typos** also cause failure (they're in baseline but not in output)
- To update the baseline after intentional changes: `make typos_known`
- `typos.toml` configures exclusions (`extend-exclude`) and known words
  (`extend-words`) that are project-specific false positives
