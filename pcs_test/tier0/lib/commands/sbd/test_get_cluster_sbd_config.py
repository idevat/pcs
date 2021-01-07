from unittest import TestCase

from pcs_test.tools import fixture
from pcs_test.tools.command_env import get_env_tools
from pcs_test.tools.misc import outdent

from pcs.common.reports import codes as report_codes
from pcs.lib.commands.sbd import get_cluster_sbd_config


class GetClusterSbdConfig(TestCase):
    def setUp(self):
        self.env_assist, self.config = get_env_tools(self)

    def test_different_responses(self):
        node_name_list = ["node-1", "node-2", "node-3", "node-4", "node-5"]
        (
            self.config.env.set_known_nodes(node_name_list)
            .corosync_conf.load(
                node_name_list=node_name_list,
                auto_tie_breaker=True,
            )
            .http.add_communication(
                "get_sbd_config",
                [
                    dict(
                        label="node-1",
                        output=outdent(
                            """\
                            # This file has been generated by pcs.
                            SBD_DELAY_START=no
                            SBD_OPTS="-n node-1"
                            SBD_PACEMAKER=yes
                            SBD_STARTMODE=always
                            SBD_WATCHDOG_DEV=/dev/watchdog
                            SBD_WATCHDOG_TIMEOUT=5
                            """
                        ),
                        response_code=200,
                    ),
                    dict(
                        label="node-2",
                        was_connected=False,
                        errno=7,
                        error_msg="Failed connect to node-2:2224;"
                        " No route to host",
                    ),
                    dict(
                        label="node-3",
                        output="OPTION=   value",
                        response_code=200,
                    ),
                    dict(
                        label="node-4",
                        output="# just comment",
                        response_code=200,
                    ),
                    dict(
                        label="node-5",
                        output="invalid value",
                        response_code=200,
                    ),
                ],
                action="remote/get_sbd_config",
            )
        )
        self.assertEqual(
            get_cluster_sbd_config(self.env_assist.get_env()),
            [
                {
                    "node": "node-1",
                    "config": {
                        "SBD_WATCHDOG_TIMEOUT": "5",
                        "SBD_WATCHDOG_DEV": "/dev/watchdog",
                        "SBD_PACEMAKER": "yes",
                        "SBD_OPTS": '"-n node-1"',
                        "SBD_STARTMODE": "always",
                        "SBD_DELAY_START": "no",
                    },
                },
                {
                    "node": "node-3",
                    "config": {
                        "OPTION": "value",
                    },
                },
                {
                    "node": "node-4",
                    "config": {},
                },
                {
                    "node": "node-5",
                    "config": {},
                },
                {
                    "node": "node-2",
                    "config": None,
                },
            ],
        )

        self.env_assist.assert_reports(
            [
                fixture.warn(
                    report_codes.NODE_COMMUNICATION_ERROR_UNABLE_TO_CONNECT,
                    node="node-2",
                    reason="Failed connect to node-2:2224; No route to host",
                    command="remote/get_sbd_config",
                ),
                fixture.warn(
                    report_codes.UNABLE_TO_GET_SBD_CONFIG,
                    node="node-2",
                    reason="",
                ),
            ]
        )

    def test_some_node_names_missing(self):
        (
            self.config.env.set_known_nodes(["rh7-2"])
            .corosync_conf.load(filename="corosync-some-node-names.conf")
            .http.add_communication(
                "get_sbd_config",
                [
                    dict(
                        label="rh7-2",
                        output="OPTION=value",
                        response_code=200,
                    ),
                ],
                action="remote/get_sbd_config",
            )
        )

        result = get_cluster_sbd_config(self.env_assist.get_env())
        self.assertEqual(
            result,
            [
                {"node": "rh7-2", "config": {"OPTION": "value"}},
            ],
        )

        self.env_assist.assert_reports(
            [
                fixture.warn(
                    report_codes.COROSYNC_CONFIG_MISSING_NAMES_OF_NODES,
                    fatal=False,
                ),
            ]
        )

    def test_all_node_names_missing(self):
        self.config.corosync_conf.load(filename="corosync-no-node-names.conf")

        self.env_assist.assert_raise_library_error(
            lambda: get_cluster_sbd_config(self.env_assist.get_env())
        )
        self.env_assist.assert_reports(
            [
                fixture.warn(
                    report_codes.COROSYNC_CONFIG_MISSING_NAMES_OF_NODES,
                    fatal=False,
                ),
                fixture.error(
                    report_codes.COROSYNC_CONFIG_NO_NODES_DEFINED,
                ),
            ]
        )
