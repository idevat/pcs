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

### Report Message Catalog

Report messages are defined in `pcs/common/reports/messages.py` — each is a
frozen dataclass inheriting from `ReportItemMessage`, with a corresponding code
in `pcs/common/reports/codes.py`.

The catalog is large and organized by domain area. Before creating a new message
type, search existing messages for a semantic match. Many common situations
(node communication failures, invalid input, missing configuration) already have
established messages with consistent wording and structure.

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

## Key Directories

- `pcs/` - CLI entry point
- `pcs/lib/` - Core library (business logic)
- `pcs/lib/commands/` - Library commands (invoked by daemon)
- `pcs/daemon/` - pcsd daemon (Tornado server)
- `pcs/daemon/app/` - HTTP handlers
- `pcs/daemon/async_tasks/` - Async task processing
- `pcsd/` - Ruby legacy daemon code
