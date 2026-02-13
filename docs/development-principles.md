# Development Principles

## Core Values

### Stability and Compatibility

- **Breaking changes are avoided** - users rely on stable workflows
- When breaking changes are necessary, they are announced in advance
- Architecture evolves incrementally while keeping the application functional
- We depend on: Linux, Pacemaker, Corosync, Python, Ruby (legacy)

### Application, Not Library

- We optimize for **readable, purposeful code**, not "perfect abstractions"
- Avoid speculative generality - solve actual problems, not hypothetical ones
- Our environment is Linux - we don't consider other platforms
- Build system: autotools

### Readability Through Simplicity

Extraction (into helpers, types, layers) is a tool for readability, not a goal
in itself. The test for whether to extract:

- **Extract when** the extracted code is noise that obscures the main logic —
  the reader can understand the main method *without* reading the helper
  (e.g. logging details, serialization boilerplate)
- **Don't extract when** the reader would need to read both the main method
  and the helper to understand either one — this just distributes complexity
  across more places

Prefer one clear method over multiple "clean" ones if the reader has to read
all of them anyway. New types (NamedTuples, dataclasses) for internal return
values earn their keep when used in multiple places or when the anonymous
alternative is genuinely confusing — not as a default practice.

## Language: Python

- **Use Python idiomatically** - don't import patterns from C, Java, etc.
- Write Python the Python way
- Take advantage of Python's strengths (duck typing, comprehensions, context
  managers, etc.)
- **Type annotations** use `typing` module forms (`Optional[X]`, `List[X]`,
  `Dict[K, V]`) for compatibility with older Python versions we support — not
  the newer `X | None`, `list[X]` syntax

## Dependencies

- **Minimize dependencies** - the app is maintained long-term
- Each dependency has its own lifecycle, complicating maintenance
- Only add dependencies when the value clearly justifies the cost

## Comments

Comments should add value, not noise.

### When to Write Comments

**Formal documentation comments:**
- Required for public interfaces (e.g., library commands in `pcs/lib/commands`
  exposed via `pcs/daemon/async_tasks/worker/command_mapping.py`)
- Must add value beyond what's obvious from the function signature - don't just
  restate parameter names and types

**Inline comments:**
- Write **why**, not **what** or **how**
- Explain why you didn't use an obvious alternative
- Explain why code can't be simplified
- Explain non-obvious constraints or requirements

### When NOT to Write Comments

- Don't repeat what's obvious from the code
- Don't document what's visible a few lines away
- Don't write documentation comments for internal functions

**Bad example:**
```python
def set_name(self, name: str) -> None:
    """
    Setting name to instance of XY
    string name -- name for XY
    """
```

**Good example:**
```python
# We can't use argparse here because we need to parse partial
# command lines while the full syntax is still being built
```

## Testing

Follow existing test patterns in the codebase. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for running tests.

## Identifying Current vs. Legacy Patterns

Not all Python code reflects the target architecture. When looking for
implementation patterns, prefer:

- **APIv2 handlers** (`pcs/daemon/app/api_v2.py`) over APIv0/v1 handlers
- **`ApiV2Client`** for node-to-node communication over `NodeCommunicator`
- **DTO-based data exchange** over raw dicts
- **Recent `pcs/lib/commands/`** implementations over older ones

The two communication pipelines have distinct sets of utilities. When writing
new cross-node communication code, use the APIv2 pipeline:

**Legacy pipeline (NodeCommunicator):**
- `NodeCommunicator`, `NodeCommunicatorFactory`
- `NodeTargetLibFactory`, `RequestTarget`
- `RunRemotelyBase` and communication command classes in
  `pcs/lib/communication/`
- pycurl-based, synchronous

**APIv2 pipeline:**
- `ApiV2Client` (`env.api_v2_client`)
- `PcsKnownHost` from `env.get_known_hosts()`
- urllib-based, async-ready

New library commands for cross-node operations should use the APIv2 pipeline.

Legacy code is functional and valuable as a knowledge source (domain logic, edge
cases), but its structure and patterns should not be replicated in new code.
When in doubt, check `docs/architecture.md` for the documented target patterns.

## General Guidance

- Respect legacy code - it's functional and serves users
- Don't refactor working code unless there's a clear reason
- When in doubt, look at recent code for patterns
- Entries in `Makefile.am` file lists are kept in alphabetical order
