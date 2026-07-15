# Reports

Source: `pcs/common/reports/`

Reports are the primary mechanism for communicating outcomes (errors, warnings,
info) from library commands back to the caller.

## Key components

- **`ReportItem`** (`pcs/common/reports/item.py`) — domain object representing
  a single report with severity, message, and optional node context
- **`ReportItemDto`** (`pcs/common/reports/dto.py`) — serializable DTO for
  transport over APIv2
- **`ReportProcessor`** (`pcs/common/reports/processor.py`) — abstract
  processor; commands use `env.report_processor` to report items
- **`report_dto_to_item()`** (`pcs/common/reports/conversions.py`) — converts
  `ReportItemDto` back to `ReportItem`, optionally adding
  `ReportItemContext` (node provenance)

## Error signaling: LibraryError and reports

`LibraryError` (`pcs/lib/errors.py`) is a flow-control signal — it carries no
user-facing information itself. Commands report errors (and other severities)
via `env.report_processor` as they go, accumulating as much information as
possible (e.g. multiple validation errors) in a single run. When a command
reaches a state where continuing no longer makes sense due to previously
reported errors, it raises `LibraryError()` to abort. The typical pattern is:

```python
if env.report_processor.report_list(report_list).has_errors:
    raise LibraryError()
```

`ReportProcessor` tracks whether any error-severity report has been seen
(`has_errors` property). This allows commands to report multiple errors before
deciding to stop, giving users the most complete feedback possible.

**`ReportProcessor` is stateless beyond `has_errors`** — it does not store or
provide access to previously reported items. The `report()` and `report_list()`
methods dispatch each item immediately (to console, log, or in-memory buffer
depending on the subclass) but the base class retains only the error flag. When
a command needs to track whether specific actions occurred (e.g. "was any element
modified?"), use local state (booleans, counters) rather than querying the
report processor.

## Forceable errors (force override pattern)

Some validations should block command execution by default but allow the user
to override with CLI's `--force`. Without `--force` the report has ERROR
severity (with a `force_code` hint telling the user which flag overrides it);
with `--force` it becomes a WARNING and the command continues.

The command accepts a `force_flags` parameter and uses `get_severity()` to
decide between error and warning:

```python
from pcs.common import reports
from pcs.lib.errors import LibraryError

def my_command(
    env: LibraryEnvironment,
    ...,
    force_flags: reports.types.ForceFlags = (),
) -> None:
    report_processor = env.report_processor

    if something_suspicious:
        report_processor.report(
            reports.ReportItem(
                severity=reports.item.get_severity(
                    reports.codes.FORCE,
                    reports.codes.FORCE in force_flags,
                ),
                message=reports.messages.SomethingSuspicious(...),
            )
        )
        if report_processor.has_errors:
            raise LibraryError()
```

Key elements:
- **`force_flags: reports.types.ForceFlags = ()`** — collection of force codes;
  empty by default (no override)
- **`reports.item.get_severity(force_code, is_forced)`** — returns WARNING
  severity when `is_forced` is `True`, ERROR with `force_code` when `False`
- **`if report_processor.has_errors: raise LibraryError()`** — stops execution
  if the report was an error (i.e. user didn't use `--force`)

There is also `reports.item.get_severity_from_flags(force_code, force_flags)`
which combines the lookup — it checks whether `force_code` is in
`force_flags`. Use whichever reads better in context.

The forceable error pattern gives users maximum feedback before aborting.
A command may report multiple forceable errors before raising `LibraryError()`
— the user sees all issues at once, not one at a time.

See [cli.md](cli.md) for how the CLI propagates `--force` to library commands.

## Report message catalog

Report messages are defined in `pcs/common/reports/messages.py` — each is a
frozen dataclass inheriting from `ReportItemMessage`, with a corresponding code
in `pcs/common/reports/codes.py`.

The catalog is large and organized by domain area. Before creating a new message
type, search existing messages for a semantic match. Many common situations
(node communication failures, invalid input, missing configuration) already have
established messages with consistent wording and structure.

### Adding a new report message

Three files must be updated (an `AllClassesTested` meta-test enforces the test):

1. **`pcs/common/reports/codes.py`** — add code constant (alphabetical order)
2. **`pcs/common/reports/messages.py`** — add `@dataclass(frozen=True)` class
   inheriting `ReportItemMessage`, grouped with related messages
3. **`pcs_test/tier0/common/reports/test_messages.py`** — add test class with
   the **same name** as the message class, inheriting `NameBuildTest`

## Forwarding remote reports

When a command receives reports from a remote node (e.g. via APIv2), the
established pattern is:

```python
context = reports.ReportItemContext(node_label)
report_list = [
    reports.report_dto_to_item(report, context)
    for report in remote_reports
]
env.report_processor.report_list(report_list)
```

Examples: `pcs/lib/communication/scsi.py`,
`pcs/lib/communication/cluster.py`,
`pcs/lib/communication/pcs_cfgsync.py`.
