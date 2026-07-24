# CIB (Cluster Information Base)

## CIB-modifying commands

Commands that modify CIB follow this pattern:

```python
def my_command(env: LibraryEnvironment, ...) -> None:
    cib = env.get_cib()
    # validate input, consider existing CIB elements
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
silently inserts an empty `<fencing-topology/>` into the CIB. Read-only commands
must not push CIB to prevent such unwanted modifications.

When a command only needs to **read** elements in an optional section
(without adding/removing), it is simpler to use XPath instead:

```python
# Read-only: iterate fencing levels without creating fencing-topology
for element in cib.findall(f".//{TAG_FENCING_LEVEL}"):
    ...

# Read-only: check whether an optional section exists and has content
acl_section = cib.find(f".//{TAG_ACLS}")
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
is guaranteed to exist structurally. Use `assert` over `cast` for this —
it provides a runtime check instead of silently hiding a potential error.
Explain in a comment that the parent is guaranteed to exist and the assert is
there to narrow the type for the purposes of static type check (mypy):

```python
# findall path includes the parent tag — parent is guaranteed to exist
for child_el in cib.findall(f".//{TAG_PARENT}/child[@attr='value']"):
    parent = child_el.getparent()
    # mypy would complain, but the parent exists: //{TAG_PARENT}/child
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
- Encapsulates non-trivial CIB structural knowledge (element creation and
  validation, complex queries, format-specific parsing)
- Has or will likely have multiple callers
- Can stand alone without `LibraryEnvironment` or reporting context

Good examples: `constraint/location.create_plain_with_rule()` (complex element
construction with validation split), `alert.validate_create_alert()` /
`alert.create_alert()` (matched validate / create pair),
`node.get_node_names()` (reusable query).

**Keep in `pcs/lib/commands/`** when code:
- Is simple XML manipulation (XPath query + attribute set) tightly coupled to
  a specific business operation and its reporting
- Has a single caller with no foreseeable reuse
- Would require passing `ReportProcessor` or creating a new return type just
  to separate it from the command

A simple XPath query in a command function is acceptable — not every line that
"knows about CIB structure" needs extraction.

### Validation and modification split

Each domain operation is split into two functions with closely aligned
interfaces:

- **`validate_*()`** — checks inputs, returns `ReportItemList`. Never modifies
  the CIB. Never raises on validation failure — it collects all problems and
  returns them so the caller can decide what to do.
- **`create_*()`** / **`update_*()`** — assumes validation has passed, modifies
  the CIB, and returns the created or modified element.

```python
# In pcs/lib/cib/<domain>.py

def validate_create_foo(
    id_provider: IdProvider,
    some_id: Optional[str],          # Optional: validator reports if missing
    options: validate.TypeOptionMap,  # may contain ValuePair for normalization
    parent_el: Optional[_Element],   # looked-up element (or None if not found)
    force_flags: ...,
) -> reports.ReportItemList:
    ...

def create_foo(
    parent_element: _Element,        # where to attach the new element
    id_provider: IdProvider,
    some_id: str,                    # not Optional: validation guarantees presence
    options: Mapping[str, str],      # plain strings (normalized values only)
    cib_schema_version: Version,
) -> _Element:
    ...
```

Key differences between the two signatures:

- **Optionality** — Validation accepts `Optional` types for user-provided
  mandatory values (and reports errors if missing). Modification accepts
  non-optional types, relying on preceding validation.
- **Option maps** — Validation accepts `validate.TypeOptionMap` (which may
  contain `ValuePair`s for normalization tracking). Modification accepts
  `Mapping[str, str]` (plain normalized values, after `pairs_to_values`).
- **Element parameters** — Validation may accept a looked-up element as
  `Optional[_Element]` (reporting an error when `None`). Modification takes a
  non-optional parent or section element for XML attachment.

When validation produces intermediate results needed by the modification
function (e.g. a parsed rule), use a **validator class** instead of a plain
function:

```python
class ValidateCreateFoo:
    def __init__(self, id_provider: IdProvider, raw_input: str, ...):
        ...

    def validate(self, force_flags: ...) -> reports.ReportItemList:
        ...

    def get_parsed_input(self) -> ParsedResult:
        """Accessor for intermediate results computed during validation."""
        ...
```

The caller uses the class like:

```python
validator = ValidateCreateFoo(id_provider, raw_input, ...)
env.report_processor.report_list(validator.validate(force_flags))
if env.report_processor.has_errors:
    raise LibraryError()
new_el = create_foo(section, id_provider, ..., validator.get_parsed_input())
```

The command layer is responsible for orchestrating the two calls:

```python
def my_command(env: LibraryEnvironment, ...) -> None:
    cib = env.get_cib()
    id_provider = IdProvider(cib)

    # 1. Validate
    env.report_processor.report_list(
        domain.validate_create_foo(id_provider, ...)
    )
    if env.report_processor.has_errors:
        raise LibraryError()

    # 2. Modify CIB (only reached when validation passed)
    domain.create_foo(section, id_provider, ...)

    env.push_cib()
```

For reference implementations of this pattern:

| Function              | Location                                    | Demonstrates                                              |
|-----------------------|---------------------------------------------|-----------------------------------------------------------|
| `set_properties`      | `pcs/lib/commands/cluster_property.py`       | Validation / modification split                           |
| `create_alert`        | `pcs/lib/commands/alert.py`                  | Validation / modification split, `IdProvider`             |
| `create_plain_with_rule` | `pcs/lib/commands/constraint/location.py` | Validator class with intermediate results, `IdProvider`   |
| `create_with_set`     | `pcs/lib/commands/constraint/ticket.py`      | Multi-step validation, value normalization, `IdProvider`  |

### `IdProvider`

`IdProvider` (`pcs/lib/cib/tools.py`) tracks CIB element IDs and prevents
collisions. It is essential for the validation / modification split because
both phases need a shared view of which IDs are available.

```python
id_provider = IdProvider(cib)
```

It provides two operations:

- **`book_ids(*ids)`** — verifies that the given IDs are not already used in
  the CIB or previously booked, and reserves them. Returns a `ReportItemList`
  with errors for any conflicts. Validators call this (typically via
  `validate.ValueId`) when the user provides a specific ID.
- **`allocate_id(proposed_id)`** — generates a unique ID based on the proposal
  (appending a numeric suffix if needed), checking both the CIB and the set of
  booked IDs to avoid conflicts. Returns the final ID string.

The same `IdProvider` instance is passed to both the validation function and
the modification function. IDs booked during validation are visible to
`allocate_id` during modification, so auto-generated IDs never collide with
user-specified ones:

```python
id_provider = IdProvider(cib)

# Validation phase: user-specified ID "my-alert" is booked
report_list = alert.validate_create_alert(id_provider, path, "my-alert")

# Modification phase: if another element auto-generates from "my-alert",
# allocate_id sees the booking and returns "my-alert-1" instead
alert_el = alert.create_alert(cib, id_provider, path, "my-alert")
```

When creating multiple elements in sequence (e.g. a constraint with its
rule, or multiple port mappings for a bundle), each `allocate_id` call sees
previously allocated IDs, preventing collisions even before the elements are
inserted into the CIB tree.

### Value normalization

Some commands normalize user-provided option values before validation (e.g.
lowercasing `loss-policy`, capitalizing `rsc-role`). The `ValuePair` mechanism
(`pcs/lib/validate.py`) preserves both the original and normalized forms so
that validation checks the normalized value but error messages show what the
user actually typed.

The flow is:

```python
# 1. Normalize: wrap each value in a ValuePair(original, normalized)
options_pairs = validate.values_to_pairs(
    options,
    validate.option_value_normalization({"loss-policy": str.lower}),
)

# 2. Validate using pairs — validators check .normalized, report .original
env.report_processor.report_list(
    domain.validate_create_foo(id_provider, ..., options_pairs, ...)
)

# 3. Extract normalized values for CIB modification
domain.create_foo(section, id_provider, ..., validate.pairs_to_values(options_pairs))
```

This transformation happens at the command layer. Validation functions accept
`validate.TypeOptionMap` (which may contain `ValuePair`s). Modification
functions accept plain `Mapping[str, str]`.

### Legacy note

Not all existing code follows these patterns — some older domain functions
combine validation and modification into a single call, and some command
functions contain CIB manipulation that could live in `pcs/lib/cib/`. If it
works and has a single caller, there is no reason to refactor it. Apply these
principles when writing new code or when refactoring creates a genuine
readability or reuse benefit.
