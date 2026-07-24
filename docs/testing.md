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

Library command tests use a custom mock framework (`get_env_tools`) that
replaces external dependencies while running the actual library command logic.
See [testing-library-framework.md](testing-library-framework.md) for the full
guide: test structure, CIB/corosync configuration, report assertions, fixtures,
and test strategy.

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
[reports.md — Adding a new report message](architecture/reports.md#adding-a-new-report-message)
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
[architecture/library.md](architecture/library.md#_local-variants-for-corosyncconf-file-mode)),
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
[architecture/overview.md — Makefile.am conventions](architecture/overview.md#makefileam-conventions).
