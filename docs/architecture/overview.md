# Architecture

## Project structure

PCS consists of several components that together provide cluster management
capabilities:

### Core components

1. **CLI** (`pcs/pcs`)
   - Command-line interface for cluster management
   - Entry point: `pcs/entry_points/`
   - Command implementations: `pcs/cli/`

2. **Library** (`pcs/lib/`)
   - Core business logic
   - Commands: `pcs/lib/commands/` (invoked by both CLI and daemon)
   - Shared utilities: `pcs/common/`

3. **Daemon — pcsd** (HTTP server for remote management)
   - **Tornado daemon** (Python) — `pcs/daemon/`
     - Main implementation, actively developed
     - Entry point: `pcs/daemon/run.py`
     - Default port: 2224
   - **Ruby daemon** (legacy) — `pcsd/`
     - Original Sinatra-based implementation
     - Still runs alongside Tornado for endpoints not yet migrated
     - Being phased out

See [daemon.md](daemon.md) for daemon internals, API layers, APIv2
architecture, and authentication.

### Optional components

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

### How the components fit together

The CLI and daemon are two different entry points into the same library layer.
The CLI is used for local, interactive management; the daemon enables remote
management and async task processing over HTTP.

```
  User (CLI)         Remote client / Web UI
      │                       │
  pcs/cli/             pcs/daemon/
      │                       │
      └──── pcs/lib/commands/ ┘
                  │
            pcs/lib/cib/        (CIB manipulation)
            pcs/common/         (DTOs, reports, types)
            pcs/lib/env.py      (command dependencies container)
```

See [library.md](library.md) for how the library layer works: commands,
LibraryEnvironment, CIB access, reports, and communication. See
[cli.md](cli.md) for the CLI pipeline, routing, and middleware.

## Key directories

| Directory                 | Purpose                                   |
|---------------------------|-------------------------------------------|
| `pcs/`                    | CLI entry point                           |
| `pcs/lib/`                | Core library (business logic)             |
| `pcs/lib/commands/`       | Library commands (invoked by daemon, CLI) |
| `pcs/common/`             | Shared types, DTOs, reports               |
| `pcs/daemon/`             | pcsd daemon (Tornado server)              |
| `pcs/daemon/app/`         | HTTP handlers                             |
| `pcs/daemon/async_tasks/` | Async task processing                     |
| `pcsd/`                   | Ruby legacy daemon code                   |
| `pcs_test/`               | Test suite (see [testing.md](../testing.md)) |

## Build system

The project uses GNU Autotools. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for
setup commands (`autogen.sh`, `./configure`, `make`) and configure flags.

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

### Source vs. generated files

When modifying the build system, edit the **source** files — never the generated
ones:

| Edit these (source)        | Don't edit (generated)                          |
|----------------------------|-------------------------------------------------|
| `configure.ac`             | `configure`, `config.status`, `config.log`      |
| `Makefile.am`              | `Makefile`, `Makefile.in`                        |
| `*.in` templates           | Their output files (without `.in` suffix)        |
| `m4/*.m4` (custom macros)  | `aclocal.m4`, `autom4te.cache/`                  |

Generated files are listed in `.gitignore`. After editing any `.in` file or
`configure.ac`, re-run `./configure` (or `make` will do it automatically if
timestamps trigger autotools re-generation).

### Makefile.am conventions

- **`EXTRA_DIST`** — files included in distribution tarballs (`make dist`).
  All distributed files must be listed here (except autotools-generated ones).
- **`MAINTAINERCLEANFILES`** — generated files removed by
  `make maintainer-clean`. When a new generated file appears in the tree,
  add it here.
- Entries in list variables (`EXTRA_DIST`, `MAINTAINERCLEANFILES`, etc.) are
  kept in **alphabetical order**.

### .gitignore and tool integration

Generated and temporary files are listed in `.gitignore`. Tools like `typos`
and `ruff` respect `.gitignore` by default, so adding a file to `.gitignore`
automatically excludes it from quality checks as well.

## Quality checks

`make check` runs the full quality-check pipeline, defined as the `check-local`
target in `Makefile.am`:

```
typos_check → ruff_lint → ruff_isort_check → ruff_format_check → mypy
  → tests_tier0 → tests_tier1 → pcsd-tests
```

Individual checks can be run separately (e.g. `make typos_check`, `make mypy`).
See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full list of make targets.

### Tool configuration

| Tool    | Config file(s)              | Notes                              |
|---------|-----------------------------|------------------------------------|
| `typos` | `typos.toml`, `typos_known` | Baseline-diff approach (see below) |
| `ruff`  | `pyproject.toml`            | Linting, import sorting, formatting|
| `mypy`  | `mypy.ini`                  | Static type checking               |

### Typos checker

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

## Detailed architecture

Each major component has a dedicated document with in-depth coverage:

- [library.md](library.md) — library commands, LibraryEnvironment,
  CorosyncConfigFacade, network communication
- [cib.md](cib.md) — CIB-modifying commands, section access, CIB domain layer
- [reports.md](reports.md) — reporting system, error signaling, force override
  pattern
- [daemon.md](daemon.md) — daemon architecture, API layers (v0/v1/v2), APIv2
  in depth, authentication, command permissions
- [cli.md](cli.md) — CLI pipeline, command routing, middleware, force flags
