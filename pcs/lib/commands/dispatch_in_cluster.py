from typing import Any, List, Mapping, cast

from pcs.common import reports
from pcs.common.file import RawFileError
from pcs.common.host import PcsKnownHost
from pcs.lib.env import LibraryEnvironment
from pcs.lib.errors import LibraryError
from pcs.lib.file.instance import FileInstance
from pcs.lib.file.raw_file import raw_file_error_report
from pcs.lib.interface.config import ParserErrorException
from pcs.lib.permissions.config.facade import FacadeV2 as PcsSettingsFacade


def dispatch_to_nodes(
    env: LibraryEnvironment,
    cluster_name: str,
    cmd_payload: Mapping[str, Any],
) -> None:
    # Try nodes sequentially until success or all fail. No overall timeout -
    # APIv2 is designed for long-running tasks, individual nodes handle their
    # own timeouts and polling.
    for host in _get_known_hosts(env, _get_cluster_nodes(env, cluster_name)):
        try:
            is_success, result = _dispatch_to_node(env, host, cmd_payload)
            # We don't analyze why a node failed. Some failures (e.g.
            # cluster not running) are node-specific and another node may
            # succeed; others (e.g. invalid input) will fail everywhere.
            # Distinguishing between these cases would require fragile
            # analysis of reports that changes as new reports are added.
            if is_success:
                return result

        except env.api_v2_client.RequestError as e:
            # Our request is wrong. Doesn't make sense send to other nodes
            env.report_processor.report(
                reports.ReportItem.error(
                    reports.messages.CommandInvalidPayload(str(e))
                )
            )
            raise LibraryError() from e

        except env.api_v2_client.CommunicationError:
            continue

    env.report_processor.report(
        reports.ReportItem.error(
            reports.messages.UnableToPerformOperationOnAnyNode()
        )
    )
    raise LibraryError()


def _get_cluster_nodes(
    env: LibraryEnvironment,
    cluster_name: str,
) -> List[str]:
    pcs_settings = FileInstance.for_pcs_settings_config()

    if not pcs_settings.raw_file.exists():
        env.report_processor.report(
            reports.ReportItem.error(
                reports.messages.PcsSettingsConfDoesNotExist()
            )
        )
        raise LibraryError()

    try:
        # read_to_facade returns FacadeInterface, but we know that for
        # PCS_SETTINGS_CONF the toolbox uses PcsSettingsFacade
        facade = cast(PcsSettingsFacade, pcs_settings.read_to_facade())
    except RawFileError as e:
        env.report_processor.report(raw_file_error_report(e))
        raise LibraryError() from e
    except ParserErrorException as e:
        env.report_processor.report_list(
            pcs_settings.parser_exception_to_report_list(e)
        )
        raise LibraryError() from e

    for cluster in facade.config.clusters:
        if cluster.name == cluster_name:
            if cluster.nodes:
                return list(cluster.nodes)
            env.report_processor.report(
                reports.ReportItem.error(
                    reports.messages.ImportedClusterHasNoNodes(cluster_name)
                )
            )
            raise LibraryError()

    env.report_processor.report(
        reports.ReportItem.error(
            reports.messages.ClusterNotImportedForManagement(cluster_name)
        )
    )
    raise LibraryError()


def _get_known_hosts(
    env: LibraryEnvironment,
    node_names: List[str],
) -> list[PcsKnownHost]:
    known_hosts = env.get_known_hosts(node_names)

    if known_hosts:
        return known_hosts

    env.report_processor.report(
        reports.ReportItem.error(reports.messages.HostNotFound(node_names))
    )
    raise LibraryError()


def _dispatch_to_node(
    env: LibraryEnvironment,
    host: PcsKnownHost,
    cmd_payload: Mapping[str, Any],
) -> tuple[bool, Any]:
    node_connector = env.api_v2_client.node_connector(
        host.dest.addr, host.dest.port, host.token, host.name
    )
    task_ident = node_connector.task_create(cmd_payload)

    is_success = False
    result = None
    for poll_result in node_connector.task_result(task_ident):
        new_reports, is_success, result = poll_result
        if new_reports:
            env.report_processor.report_list(new_reports)
    return is_success, result
