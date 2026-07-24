# PCS — Developer Documentation

This documentation helps contributors (human and AI) understand the project
structure, design intent, and implementation choices.

## Where to start

1. Root [README.md](../README.md) — what PCS is, dependencies, installation
2. Root [CONTRIBUTING.md](../CONTRIBUTING.md) — development setup, running
   tests, distribution
3. [project-overview.md](project-overview.md) — ecosystem context, project
   history, and evolution
4. [development-principles.md](development-principles.md) — coding philosophy,
   conventions, identifying legacy patterns
5. [architecture/overview.md](architecture/overview.md) — project structure,
   components overview, build system, quality checks
   - [architecture/library.md](architecture/library.md) — library commands,
     LibraryEnvironment, CorosyncConfigFacade, node communication
   - [architecture/cib.md](architecture/cib.md) — CIB-modifying commands,
     section access, CIB domain layer
   - [architecture/reports.md](architecture/reports.md) — reporting system,
     error signaling, force override pattern
   - [architecture/daemon.md](architecture/daemon.md) — daemon, API layers,
     APIv2, authentication
   - [architecture/cli.md](architecture/cli.md) — CLI pipeline, routing,
     middleware
6. [testing.md](testing.md) — test tiers, frameworks, patterns, and strategies
   - [testing-library-framework.md](testing-library-framework.md) — library
     command test framework (`get_env_tools`)

## Documentation philosophy

This documentation aims for mental alignment and practical orientation. It
explains intent, structure, and context — things that are hard to see from code
alone. It does not try to duplicate what the code already says. The goal is not
to eliminate the need to read code, but to point toward the right code and
provide the context in which it becomes easy to understand.

When writing new documentation, focus on the "why" and the big picture, not on
restating implementation details.

## For AI agents

When working on PCS tasks, read documentation in this order:

1. [development-principles.md](development-principles.md) — coding guidelines
   and conventions
2. The architecture file relevant to your task area
3. [testing.md](testing.md) — how to write and run tests
