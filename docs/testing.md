# Testing

This document describes testing frameworks, patterns, and strategies for pcs.
For running tests and available make targets, see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Test tiers

Tests are organized into two tiers with different scope:

- **Tier0** (`pcs_test/tier0/`) — unit tests for all Python modules: CLI
  parsing, common utilities, daemon components, and library commands. Fast, no
  external dependencies. Library command tests use a custom mock framework
  (`get_env_tools`) described [below](#library-command-test-framework); other
  tier0 tests are standard unit tests.

- **Tier1** (`pcs_test/tier1/`) — CLI integration tests. Runs actual `pcs`
  commands via `PcsRunner` (subprocess). Tests the full pipeline: CLI routing
  → handler → lib_wrapper → library command. Verifies that the CLI layer is
  correctly wired to the library layer.

**When to use which:**

- Tier0 for unit testing all Python modules — library command logic (edge
  cases, report combinations, force patterns, CIB transformations), CLI
  parsing, common utilities, and daemon components.
- Tier1 for verifying CLI integration — that the command is routable, arguments
  are parsed correctly, and the library command is invoked with the expected
  effect.

Tier1 tests are intentionally lighter — they don't need to re-test every
scenario covered by tier0. A few representative cases (success path, error
path, usage errors) are sufficient.

## Running individual tests

Tests are run via `pcs_test/suite`. Each argument is a dotted path to a test
module, class, or method:

```bash
# Run all tests in a module
pcs_test/suite pcs_test.tier0.common.reports.test_messages

# Run a single test class
pcs_test/suite pcs_test.tier0.common.reports.test_messages.CibUpgradeSuccessful

# Run a single test method
pcs_test/suite pcs_test.tier0.common.reports.test_messages.CibUpgradeSuccessful.test_success

# Run multiple modules
pcs_test/suite pcs_test.tier0.lib.cib.test_something pcs_test.tier0.common.reports.test_messages
```

The minimum granularity is a module — a bare package path like
`pcs_test.tier0.lib.commands.cluster` is not sufficient.

To run the entire tier0 or tier1 suite, use `make tests_tier0` or
`make tests_tier1`. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full
list of make targets.

## Library command test framework

Source: `pcs_test/tier0/lib/commands/`

### Framework overview

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

### Basic test structure

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

### Configuring CIB

#### Loading CIB

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

#### Pushing modified CIB

```python
self.config.env.push_cib(
    resources="<resources>...</resources>",
    constraints="<constraints>...</constraints>",
)
```

The test framework verifies that the CIB produced by the command matches
the expected sections. Sections not specified are expected to remain unchanged
from the loaded CIB.

### Configuring corosync.conf

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

### Asserting reports

#### Success with reports

```python
lib.my_command(self.env_assist.get_env(), ...)
self.env_assist.assert_reports([
    fixture.info(reports.codes.SOMETHING_UPDATED, param="value"),
    fixture.warn(reports.codes.SOMETHING_NEEDS_ATTENTION, param="value"),
])
```

#### Error — command raises LibraryError

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

### Report fixture API

```python
fixture.error(report_code, **message_kwargs)
fixture.error(report_code, force_code=reports.codes.FORCE, **message_kwargs)
fixture.warn(report_code, **message_kwargs)
fixture.info(report_code, **message_kwargs)
```

The `**message_kwargs` must match the fields of the corresponding
`ReportItemMessage` dataclass in `pcs/common/reports/messages.py`.

### CIB XML fixtures

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

### Named calls and call replacement

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

### Test strategy for CIB-modifying commands

Recommended test cases:

1. **Success with minimal parameters** — command works with required args only
2. **Success with all parameters** — exercises all optional features
3. **Success with maximum reports** — verifies all info/warning reports
4. **Error cases** — invalid input, missing elements, validation failures
5. **Non-live CIB** — if command supports `-f` flag, test file-based CIB

## Testing report messages

Source: `pcs_test/tier0/common/reports/test_messages.py`

Report messages (`pcs/common/reports/messages.py`) have their own tests. Each
message class needs a test class with the **same name**, inheriting from
`NameBuildTest`:

```python
class MyNewReportMessage(NameBuildTest):
    def test_success(self):
        self.assertEqual(
            "Expected human-readable message text",
            reports.MyNewReportMessage("param1", "param2").message,
        )
```

The `AllClassesTested` meta-test automatically verifies that every
`ReportItemMessage` subclass has a corresponding test class. Missing tests
cause a test failure. See
[architecture_library.md — Adding a new report message](architecture_library.md#adding-a-new-report-message)
for the full checklist.

## CLI integration tests (tier1)

Source: `pcs_test/tier1/`

### Framework components

| Module                      | Purpose                                                      |
|-----------------------------|--------------------------------------------------------------|
| `pcs_test.tools.pcs_runner` | `PcsRunner` — runs `pcs` commands with `-f` CIB file         |
| `pcs_test.tools.assertions` | `AssertPcsMixin` — `assert_pcs_success`, `assert_pcs_fail`   |
| `pcs_test.tools.misc`       | `get_test_resource`, `get_tmp_file`, `write_file_to_tmpfile` |
| `pcs_test.tools.xml`        | `str_to_etree` — parse XML for verification                  |

### Basic test structure

```python
from unittest import TestCase

from pcs_test.tools.assertions import AssertPcsMixin
from pcs_test.tools.misc import (
    get_test_resource,
    get_tmp_file,
    write_file_to_tmpfile,
)
from pcs_test.tools.pcs_runner import PcsRunner
from pcs_test.tools.xml import str_to_etree


class MyCommandTest(AssertPcsMixin, TestCase):
    def setUp(self):
        self.temp_cib = get_tmp_file("tier1_my_test")
        write_file_to_tmpfile(get_test_resource("cib-all.xml"), self.temp_cib)
        self.pcs_runner = PcsRunner(self.temp_cib.name)

    def tearDown(self):
        self.temp_cib.close()

    def test_success(self):
        self.assert_pcs_success(
            ["area", "subcommand", "arg1", "arg2"],
            stderr_full="Expected output\n",
        )

    def test_error(self):
        self.assert_pcs_fail(
            ["area", "subcommand"],
            stderr_start="\nUsage: pcs area",
        )
```

Key details:
- `PcsRunner(cib_file)` automatically injects `-f cib_file` into every command
- `PcsRunner` also accepts `corosync_conf_opt` for commands using
  `--corosync_conf`
- `AssertPcsMixin` provides `assert_pcs_success` (return code 0) and
  `assert_pcs_fail` (return code 1)
- Both methods support `stdout_full`, `stderr_full`, `stderr_start`,
  `stderr_regexp` for output assertions

### Verifying CIB changes

For CIB-modifying commands, read back the temp file and verify via XPath:

```python
def test_modifies_cib(self):
    self.assert_pcs_success(["area", "subcommand", "arg1"])

    self.temp_cib.seek(0)
    cib_tree = str_to_etree(self.temp_cib.read())

    self.assertEqual(len(cib_tree.xpath("//element[@attr='new']")), 1)
    self.assertEqual(len(cib_tree.xpath("//element[@attr='old']")), 0)
```

### Verifying corosync.conf changes

For commands with `--corosync_conf` support (those with a `_local` library
variant — see
[architecture_library.md](architecture_library.md#_local-variants-for-corosyncconf-file-mode)),
write a fixture to a temp file and verify the result after running:

```python
class MyLocalCommand(AssertPcsMixin, TestCase):
    def setUp(self):
        self.corosync_conf_file = get_tmp_file("tier1_my_test_corosync.conf")
        self.pcs_runner = PcsRunner(
            cib_file=None,
            corosync_conf_opt=self.corosync_conf_file.name,
        )

    def tearDown(self):
        self.corosync_conf_file.close()

    def test_modifies_corosync_conf(self):
        write_data_to_tmpfile(fixture_corosync_conf(), self.corosync_conf_file)
        self.assert_pcs_success(["area", "subcommand", "arg1"])
        self.assertEqual(self.corosync_conf_file.read(), expected_content)
```

Reference: `pcs_test/tier1/cluster/test_config_update.py`

### CIB fixture files

Test CIB files are in `pcs_test/resources/`:

| File | Content |
|------|---------|
| `cib-empty.xml` | Minimal CIB, no nodes |
| `cib-empty-withnodes.xml` | Minimal CIB with 2 nodes (rh7-1, rh7-2) |
| `cib-empty-with3nodes.xml` | Minimal CIB with 3 nodes |
| `cib-all.xml` | Rich CIB with resources, constraints, alerts, etc. |

Prefer existing fixtures over creating new ones. `cib-all.xml` covers most
CLI integration testing needs.

## Techniques

### Test consolidation

*When: a command has multiple independent effects (e.g. renames across
locations, rule expressions, fencing levels)*

Consolidate into fewer, broader tests rather than writing a separate test
class for each effect:

- **One "success" test** that exercises all effects at once, with irrelevant
  items mixed in to verify selectivity. This catches regressions in any
  single effect and verifies they compose correctly.
- **One "no match" test** that populates CIB with items that *look* related
  but don't match (different node name, different attribute, wrong element
  type). This verifies that the command does not modify irrelevant data.
- **Separate classes** for corner cases that need different test setup
  (e.g. missing corosync.conf, `-f` mode).

The tradeoff: a failing consolidated test is less specific about *which*
effect broke. This is acceptable — the test failure message and CIB diff
provide enough signal to locate the issue, and the reduced test count makes
the suite easier to maintain as the command grows.

### Force pattern testing

*When: testing a command that supports `--force` override (forceable errors)*

The force pattern requires two test cases — one without force (expects error)
and one with force (expects warning and command proceeds). See
[architecture_library.md — Forceable errors](architecture_library.md#forceable-errors-force-override-pattern)
for how the pattern works in library code.

```python
# Without force — error
self.env_assist.assert_raise_library_error(
    lambda: lib.my_command(self.env_assist.get_env(), ...)
)
self.env_assist.assert_reports([
    fixture.error(
        reports.codes.SOME_ERROR,
        force_code=reports.codes.FORCE,
        param="value",
    ),
])

# With force — warning, command proceeds
self.config.env.push_cib(resources="...")
lib.my_command(self.env_assist.get_env(), ..., force_flags=[reports.codes.FORCE])
self.env_assist.assert_reports([
    fixture.warn(reports.codes.SOME_ERROR, param="value"),
])
```

### Testing with non-live CIB

*When: testing a command that supports the `-f` flag (file-based CIB) in
tier0*

```python
cib = modify_cib(read_test_resource("cib-empty.xml"), resources="...")
self.config.env.set_cib_data(cib)
self.config.runner.cib.load_content(cib, env={"CIB_file": "/fake/tmp/file"})
self.config.env.push_cib(resources="...", load_key="runner.cib.load_content")
```

When testing `-f` mode for a command that gates corosync access on
`env.is_cib_live`, using `set_cib_data()` means the command should skip
corosync access — no `set_corosync_conf_data()` call is needed:

```python
def test_cib_from_file_skips_corosync_check(self):
    cib_xml = "<cib>...</cib>"
    self.config.env.set_cib_data(cib_xml)
    self.config.runner.cib.load_content(
        cib_xml, env={"CIB_file": "/fake/tmp/file"}
    )
    self.config.env.push_cib(
        ..., load_key="runner.cib.load_content"
    )
    lib.my_command(self.env_assist.get_env(), ...)
```

See
[architecture_library.md — Conditionally using non-CIB data sources](architecture_library.md#conditionally-using-non-cib-data-sources)
for the library-side pattern.

### Testing live-only commands

*When: testing a tier1 command that calls `ensure_live_env(env)` and rejects
both `-f` and `--corosync_conf`*

These commands can't do end-to-end file-based verification. Instead, test:

1. **Usage errors** — wrong argument count
2. **Unsupported option rejection** — passing `-f` or `--corosync_conf`
   triggers `modifiers.ensure_only_supported()`, proving the CLI handler
   is actually invoked and wired correctly

```python
class MyLiveOnlyCommand(AssertPcsMixin, TestCase):
    def setUp(self):
        self.pcs_runner = PcsRunner(cib_file=None)

    def test_usage_error_no_args(self):
        self.assert_pcs_fail(
            ["area", "subcommand"],
            stderr_start="\nUsage: pcs area",
        )

    def test_not_live_pcmk(self):
        self.pcs_runner = PcsRunner(
            cib_file=get_test_resource("cib-empty.xml"),
        )
        self.assert_pcs_fail(
            ["area", "subcommand", "arg1", "arg2"],
            stderr_full=(
                "Error: Specified option '-f' is not supported in this "
                "command\n"
            ),
        )

    def test_not_live_corosync(self):
        self.pcs_runner = PcsRunner(
            cib_file=None,
            corosync_conf_opt=get_test_resource("corosync_conf"),
        )
        self.assert_pcs_fail(
            ["area", "subcommand", "arg1", "arg2"],
            stderr_full=(
                "Error: Specified option '--corosync_conf' is not supported "
                "in this command\n"
            ),
        )
```

Reference: `pcs_test/tier1/cluster/test_cluster_rename.py`

## Makefile.am file lists

When adding a new test file, add it to `pcs_test/Makefile.am`. Similarly, new
source files under `pcs/` must be listed in `pcs/Makefile.am`. Both Makefiles
list every `.py` file individually. Missing this step won't cause test or lint
failures — it causes packaging/distribution failures that surface late. See
[architecture.md — Makefile.am conventions](architecture.md#makefileam-conventions).
