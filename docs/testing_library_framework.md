# Library command test framework

Source: `pcs_test/tier0/lib/commands/`

## Framework overview

Library command tests use a custom test environment that mocks external
dependencies while running the actual library command logic. This allows
integration-style testing of complete commands without a live cluster.

Key modules:

| Module | Purpose |
|--------|---------|
| `pcs_test.tools.command_env` | `get_env_tools` — main entry point |
| `pcs_test.tools.fixture` | Report assertion helpers (`error`, `warn`, `info`) |
| `pcs_test.tools.fixture_cib` | CIB XML manipulation (`modify_cib`) |
| `pcs_test.tools.misc` | `read_test_resource`, `get_test_resource` |

## Basic test structure

```python
from unittest import TestCase

from pcs.common import reports
from pcs.lib.commands import mymodule as lib

from pcs_test.tools import fixture
from pcs_test.tools.command_env import get_env_tools


class MyCommandTest(TestCase):
    def setUp(self):
        self.env_assist, self.config = get_env_tools(self)

    def test_success(self):
        # 1. Configure expectations (what external calls will happen)
        self.config.runner.cib.load(resources="<resources>...</resources>")
        self.config.env.push_cib(resources="<resources>...</resources>")

        # 2. Execute the command
        lib.my_command(self.env_assist.get_env(), ...)

        # 3. Assert reports (optional — empty list means silent success)
        self.env_assist.assert_reports([])
```

`get_env_tools(self)` returns two objects:
- **`env_assist`** — provides `get_env()` (creates the `LibraryEnvironment`),
  `assert_reports()`, and `assert_raise_library_error()`
- **`config`** — fluent API for configuring mock expectations

## Configuring CIB

### Loading CIB

```python
# Load with section overrides (most common)
self.config.runner.cib.load(
    resources="<resources>...</resources>",
    constraints="<constraints>...</constraints>",
    fencing_topology="<fencing-topology>...</fencing-topology>",
    optional_in_conf="<acls>...</acls>",
)

# Load from fixture file
from pcs_test.tools.fixture_cib import modify_cib
from pcs_test.tools.misc import read_test_resource

cib = modify_cib(
    read_test_resource("cib-empty.xml"),
    resources="<resources>...</resources>",
)
self.config.runner.cib.load_content(cib)
```

Available section parameters for `load()`: `resources`, `constraints`, `nodes`,
`crm_config`, `tags`, `fencing_topology`, `acls`, `optional_in_conf`, `status`.

These are defined in `MODIFIER_GENERATORS` in `pcs_test/tools/fixture_cib.py`.
Mandatory sections (`resources`, `constraints`, `nodes`, `crm_config`) use
`replace_all` — they replace an existing section in the base CIB. Optional
sections (`fencing_topology`, `tags`, `acls`) use `put_or_replace` — they
insert the section if absent, or replace it if present.

`optional_in_conf` works the same way as the named optional-section shortcuts
(`fencing_topology`, `acls`, `tags`) — it inserts a section under
`<configuration>` if absent, or replaces it if present. Use it when no named
shortcut exists for the section you need:

```python
self.config.runner.cib.load(
    optional_in_conf="<alerts>...</alerts>",
)
```

Since each keyword argument can only appear once, use the named shortcuts
when a test needs multiple optional sections simultaneously:

```python
self.config.runner.cib.load(
    fencing_topology="<fencing-topology>...</fencing-topology>",
    acls="<acls>...</acls>",
)
```

### Pushing modified CIB

```python
self.config.env.push_cib(
    resources="<resources>...</resources>",
    constraints="<constraints>...</constraints>",
)
```

The test framework verifies that the CIB produced by the command matches
the expected sections. Sections not specified are expected to remain unchanged
from the loaded CIB.

## Configuring corosync.conf

When a library command reads corosync.conf (via `env.get_corosync_conf()`),
tests must provide mock data. Without it, the framework would attempt to read
the real `/etc/corosync/corosync.conf`.

```python
self.config.env.set_corosync_conf_data(corosync_conf_text)
```

This sets `corosync_conf_data` on the `LibraryEnvironment` constructor,
making `env.is_corosync_conf_live` return `False` and
`env.get_corosync_conf()` parse the provided text.

A minimal corosync.conf for tests:

```python
def _corosync_conf(*node_names):
    nodes = "\n".join(
        f"""\
        node {{
            ring0_addr: {name}
            nodeid: {i}
            name: {name}
        }}"""
        for i, name in enumerate(node_names, 1)
    )
    return f"""\
        totem {{
            version: 2
            cluster_name: test
            transport: udpu
        }}
        
        nodelist {{
        {nodes}
        }}
        
        quorum {{
            provider: corosync_votequorum
        }}
    """
```

## Asserting reports

### Success with reports

```python
lib.my_command(self.env_assist.get_env(), ...)
self.env_assist.assert_reports([
    fixture.info(reports.codes.SOMETHING_UPDATED, param="value"),
    fixture.warn(reports.codes.SOMETHING_NEEDS_ATTENTION, param="value"),
])
```

### Error — command raises LibraryError

```python
self.env_assist.assert_raise_library_error(
    lambda: lib.my_command(self.env_assist.get_env(), ...)
)
self.env_assist.assert_reports([
    fixture.error(reports.codes.SOME_ERROR, param="value"),
])
```

`assert_raise_library_error` verifies that `LibraryError` is raised. Reports
are checked separately via `assert_reports`.

## Report fixture API

```python
fixture.error(report_code, **message_kwargs)
fixture.error(report_code, force_code=reports.codes.FORCE, **message_kwargs)
fixture.warn(report_code, **message_kwargs)
fixture.info(report_code, **message_kwargs)
```

The `**message_kwargs` must match the fields of the corresponding
`ReportItemMessage` dataclass in `pcs/common/reports/messages.py`.

## CIB XML fixtures

Choose the fixture approach based on whether the data varies across tests:

- **Constants** — for fixed XML that is the same in every test. Good for
  structural elements that don't change (e.g. a static resource definition).
- **Helper functions** — for XML that varies by parameters (node names, IDs,
  attribute values). When the same element needs to appear with different
  values across tests, a helper avoids proliferating `_OLD` / `_NEW` /
  `_OTHER` constant variants.

Prefer helpers when the element participates in rename/update logic — the
test needs both "before" and "after" versions and potentially "irrelevant"
versions with different parameters. Constants lead to combinatorial explosion.

```python
# Constant — element doesn't vary
FIXTURE_RESOURCES = """
    <resources>
        <primitive id="R1" class="ocf" provider="heartbeat" type="Dummy"/>
    </resources>
"""

# Helper — element varies by parameters
def _location(location_id, node_name):
    return (
        f'<rsc_location id="{location_id}" rsc="R"'
        f' node="{node_name}" score="100"/>'
    )
```

Common CIB fixture files in `pcs_test/resources/`: `cib-empty.xml`,
`cib-empty-withnodes.xml`, `cib-all.xml`.

## Named calls and call replacement

For tests needing multiple CIB loads or complex call sequences:

```python
# Name a call for later reference
self.config.runner.cib.load(resources="...", name="first_load")

# Replace a previously configured call
self.config.runner.cib.load(
    resources="different",
    instead="first_load",
)

# Reference a specific load when pushing
self.config.env.push_cib(
    resources="...",
    load_key="runner.cib.load_content",
)
```

## Test strategy for CIB-modifying commands

Recommended test cases:

1. **Success with minimal parameters** — command works with required args only
2. **Success with all parameters** — exercises all optional features
3. **Success with maximum reports** — verifies all info/warning reports
4. **Error cases** — invalid input, missing elements, validation failures
5. **Non-live CIB** — if command supports `-f` flag, test file-based CIB
