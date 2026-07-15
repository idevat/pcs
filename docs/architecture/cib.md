# CIB (Cluster Information Base)

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

## CIB section access

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

## `findall()` vs `xpath()`

lxml offers two query methods with different capabilities:

- **`findall()`** — uses **ElementPath** (a limited subset of XPath). Supports
  attribute predicates (`[@attr='value']`) and path navigation, but **not**
  XPath functions like `contains()`, `starts-with()`, `not()`, etc. Use this
  for straightforward structural queries.
- **`xpath()`** — uses **full XPath 1.0**. Supports all XPath functions and
  axes. Use when `findall()` is insufficient.

Most CIB queries in this codebase use `findall()`, which is sufficient for
attribute-based filtering. If you need XPath functions, switch to `xpath()`.

## `getparent()` type narrowing

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
