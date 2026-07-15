# Development Principles

## Core values

### Stability and compatibility

- **Breaking changes are avoided** — users rely on stable workflows
- When breaking changes are necessary, they are announced in advance
- Architecture evolves incrementally while keeping the application functional
- We depend on: Linux, Pacemaker, Corosync, Python, Ruby (legacy)

### Application, not library

- We optimize for **readable, purposeful code**, not "perfect abstractions"
- Avoid speculative generality — solve actual problems, not hypothetical ones
- Our environment is Linux — we don't consider other platforms
- Build system: autotools (see [architecture/overview.md](architecture/overview.md) for details)

### Readability through simplicity

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

- **Use Python idiomatically** — don't import patterns from C, Java, etc.
- Write Python the Python way
- Take advantage of Python's strengths (duck typing, comprehensions, context
  managers, etc.)
- **Type annotations** use `typing` module forms (`Optional[X]`, `List[X]`,
  `Dict[K, V]`) for compatibility with older Python versions we support — not
  the newer `X | None`, `list[X]` syntax

## Dependencies

- **Minimize dependencies** — the app is maintained long-term
- Each dependency has its own lifecycle, complicating maintenance
- Only add dependencies when the value clearly justifies the cost

## Comments

Comments should add value, not noise.

### When to write comments

**Formal documentation comments:**
- Required for public interfaces (e.g., library commands in `pcs/lib/commands`
  exposed via `pcs/daemon/async_tasks/worker/command_mapping.py`)
- Must add value beyond what's obvious from the function signature — don't just
  restate parameter names and types

**Inline comments:**
- Write **why**, not **what** or **how**
- Explain why you didn't use an obvious alternative
- Explain why code can't be simplified
- Explain non-obvious constraints or requirements

### When NOT to write comments

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
[CONTRIBUTING.md](../CONTRIBUTING.md) for running tests. For library command
test framework details and strategy, see [testing.md](testing.md).

Note that many existing tests in the codebase are legacy — they may use
outdated patterns (excessive constants, one test class per feature, tight
coupling to internal structure). When looking for test patterns, prefer
the guidance in `testing.md` over copying from arbitrary existing tests.

## Identifying current vs. legacy patterns

Not all Python code reflects the target architecture. When looking for
implementation patterns, prefer:

- **APIv2 handlers** (`pcs/daemon/app/api_v2.py`) over APIv0/v1 handlers
- **DTO-based data exchange** over raw dicts
- **Recent `pcs/lib/commands/`** implementations over older ones — see the
  reference table in
  [architecture/library.md](architecture/library.md#library-commands)

Legacy code is functional and valuable as a knowledge source (domain logic, edge
cases), but its structure and patterns should not be replicated in new code.
When in doubt, check the architecture documents for the documented target
patterns.

## General guidance

- Respect legacy code — it's functional and serves users
- Don't refactor working code unless there's a clear reason
- When in doubt, look at recent code for patterns
- Entries in `Makefile.am` file lists are kept in alphabetical order

## Techniques

### Decomposing long command functions

*When: a library command function grows long enough that extracting helpers
improves readability (the reader can understand the main function without
reading the helpers).*

Extract private helpers within the same module. Follow these conventions:

**Return `ReportItemList`** from helpers that modify state and report what they
did. The main function iterates the returned list, reports it, and uses it to
track state (e.g. whether anything was modified). This is consistent with the
`pcs/lib/cib/` convention and with existing helpers in command modules.

```python
def _rename_node_in_locations(
    cib: _Element, old_name: str, new_name: str
) -> reports.ReportItemList:
    report_list: reports.ReportItemList = []
    for element in cib.findall(...):
        element.set("node", new_name)
        report_list.append(reports.ReportItem.info(...))
    return report_list

# In the main function:
for report_item in _rename_node_in_locations(cib, old_name, new_name):
    report(report_item)
    cib_updated = True
```

**Prefer eager execution over generators** for helpers that modify state.
Generators with side-effects (modifying CIB elements during iteration) are
conceptually fragile — modifications happen lazily, only when the caller
iterates. A function that eagerly performs work and returns the results is
clearer and safer: the work happens when the function is called, regardless
of how the caller uses the result.
