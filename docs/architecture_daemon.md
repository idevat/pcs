# Daemon layer

Source: `pcs/daemon/`

The pcsd daemon is a Tornado-based HTTP server that enables remote cluster
management and asynchronous task processing. It listens on port 2224 by default.

Entry point: `pcs/daemon/run.py`

## API layers

The Python daemon has three API handler layers, reflecting the project's
evolution:

- **APIv0** (`pcs/daemon/app/api_v0.py`) — oldest Python API layer, legacy
- **APIv1** (`pcs/daemon/app/api_v1.py`) — improved interface, legacy
- **APIv2** (`pcs/daemon/app/api_v2.py`) — current target architecture, async
  task processing

All three share the same backend: they create `CommandDto` and submit tasks to
the async scheduler. The difference is in their HTTP interface and client
compatibility. **New development targets APIv2.**

## Ruby legacy daemon

Source: `pcsd/`

For historical reasons (original implementation was Ruby), a second daemon runs
alongside the Tornado daemon. The Tornado daemon delegates requests to the Ruby
daemon via a Unix socket (`pcs/daemon/app/sinatra_remote.py`) when there is no
Python implementation yet.

**This is legacy** — new features should be implemented in Python, not Ruby.

## APIv2

Source: `pcs/daemon/app/api_v2.py`

APIv2 enables asynchronous HTTP request processing.

### Endpoints

- **`/api/v2/task/create`** — submit a request, get task ID immediately
- **`/api/v2/task/result`** — check task status and get results
- **`/api/v2/task/kill`** — terminate a running task
- **`/api/v2/task/run`** — synchronous execution (`task/create` + polling
  `task/result`)

### Flow

1. Client calls `task/create` with request
2. Server creates task ID and queues request
3. Server returns task ID immediately (non-blocking)
4. Request is processed asynchronously by a library command from
   `pcs/lib/commands/`
5. Client polls `task/result` with task ID to get status and report list
6. When complete, results are returned

### Data layer (DTOs, types, serialization)

APIv2 communication uses typed data structures defined in `pcs/common/`:

- **DTOs**: `pcs/common/async_tasks/dto.py` — dataclasses representing API
  payloads and responses (`CommandDto`, `TaskIdentDto`, `TaskResultDto`,
  `CommandOptionsDto`)
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

#### Domain objects vs DTOs

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

**`to_dict()` only works correctly on `DataTransferObject` instances.**
Internally it uses `dataclasses.fields()` on the *static* type annotations to
traverse fields. This means it cannot handle polymorphic domain objects — for
example, calling `to_dict()` on a `ReportItem` silently loses the `message`
content, because the annotated type `ReportItemMessage` has no dataclass fields
even though the actual runtime instance is a concrete subclass with data. Always
convert domain objects to DTOs first via `.to_dto()`.

### Response structure

`TaskResultDto` is a complete record of a task. It includes the original
command, accumulated reports, execution state, and result:

```
TaskResultDto
├── task_ident: str
├── command: CommandDto              # full original request
│   ├── command_name: str
│   ├── params: dict[str, Any]
│   └── options: CommandOptionsDto   # includes effective_username, etc.
├── reports: list[ReportItemDto]
├── state: TaskState
├── task_finish_type: TaskFinishType
├── kill_reason: Optional[TaskKillReason]
└── result: Any
```

The `command` field echoes back the entire original `CommandDto` including
`options`. This is by design — it provides a complete audit trail and enables
clients to correlate responses with requests. Both `task/result` and `task/run`
return this structure.

### Task result behavior

Each call to `task/result` returns **all accumulated reports** since task
creation — the report list is append-only and never cleared. Clients that poll
`task/result` repeatedly will receive growing lists. To identify new reports,
track the number of already-seen reports and slice from that index.

### Task lifecycle invariants

`task/create` is an **irreversible operation**. Once the server returns a task
ID, the task is queued for execution and will run regardless of whether the
client polls `task/result`. There is no "undo" — only `task/kill` can attempt
to stop a running task, and even that may arrive after execution completes.

Implications for code that creates tasks on remote nodes:

- A successful `task/create` followed by a failed `task/result` poll does
  **not** mean the task didn't execute — it means you lost visibility, not
  control
- Retry or failover logic that creates the same task on another node risks
  concurrent execution of the same operation
- Code that creates tasks on remote nodes must treat a successful `task/create`
  as a commitment to that node

## Command mapping and permissions

Source: `pcs/daemon/async_tasks/worker/command_mapping.py`

Task processing is delegated to library commands in `pcs/lib/commands/`. The
`COMMAND_MAP` maps command name strings to command functions and their required
permissions. The key format is `"<module>.<function>"` where `<module>` matches
the library commands module and `<function>` matches the function name (e.g.
`"cluster.setup"`, `"resource.create"`).

Each command has a `required_permission` that the daemon checks before execution.
Permission levels (`pcs/lib/permissions/types.py`):

- **`NONE`** — no authorization check. Used for commands that delegate
  authorization to another layer (e.g., a dispatcher forwarding to a remote
  node, where the remote node enforces its own permissions for the actual
  command)
- **`READ`** — read-only operations
- **`WRITE`** — modifying operations (implies READ)
- **`GRANT`** — permission management operations
- **`FULL`** — administrative operations (implies READ + WRITE + GRANT)
- **`SUPERUSER`** — reserved for `hacluster` (implies all)

Permission is enforced on the local node before the command runs. For commands
that forward operations to remote nodes, the remote node performs its own
independent permission check for the forwarded command.

## Authentication and user identity

### Impersonation model

pcsd-to-pcsd communication authenticates via **token** (shared secret between
nodes). The token resolves to the `hacluster` superuser. The actual user
identity (the person using CLI or Web UI) is forwarded separately:

- **Legacy (NodeCommunicator):** `CIB_user` and `CIB_user_groups` cookies
- **APIv2:** `CommandOptionsDto.effective_username` and `.effective_groups`
  fields in the JSON payload

On the receiving side, the executor (`pcs/daemon/async_tasks/worker/executor.py`)
resolves the effective user: if the authenticated user is a superuser and
`effective_username` is provided, the command runs under the effective identity.
Otherwise, it runs as the authenticated user.

### Where identity is used

`LibraryEnvironment` receives the resolved identity as `user_login` and
`user_groups`. These are used for:

- **CommandRunner** (`env.cmd_runner()`) — sets `CIB_user` environment variable
  for Pacemaker commands
- **NodeCommunicatorFactory** — creates `CIB_user`/`CIB_user_groups` cookies
  for legacy remote requests

See [architecture_library.md — Service propagation pattern](architecture_library.md#service-propagation-pattern)
for details on how `LibraryEnvironment` distributes identity to communication
layers.
