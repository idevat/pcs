from os.path import join as join_path
from functools import partial
from ssl import OP_NO_SSLv2
from unittest import TestCase, mock

from pcs import settings
from pcs.daemon import env
from pcs.test.tools.misc import create_setup_patch_mixin

class Logger:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, error):
        self.errors.append(error)

    def warning(self, warning):
        self.warnings.append(warning)


class Prepare(TestCase, create_setup_patch_mixin(env)):
    def setUp(self):
        self.socket = self.setup_patch("socket")
        self.path_exists = self.setup_patch("path_exists", return_value=True)
        self.logger = Logger()

    def assert_environ_prdoduces_modified_pcsd_env(
        self, environ=None, specific_env_values=None, errors=None, warnings=None
    ):
        pcsd_dir = partial(join_path, settings.pcsd_exec_location)
        default_env_values = {
            env.PCSD_PORT: settings.pcsd_default_port,
            env.PCSD_SSL_CIPHERS: settings.default_ssl_ciphers,
            env.PCSD_SSL_OPTIONS: env.str_to_ssl_options(
                settings.default_ssl_options,
                []
            ),
            env.PCSD_BIND_ADDR: {None},
            env.NOTIFY_SOCKET: None,
            env.PCSD_DEBUG: False,
            env.DISABLE_GUI: False,
            env.PCSD_SESSION_LIFETIME: settings.gui_session_lifetime_seconds,
            env.GEM_HOME: pcsd_dir(settings.pcsd_gem_path),
            env.PCSD_CMDLINE_ENTRY: pcsd_dir(env.PCSD_CMDLINE_ENTRY_RB_SCRIPT),
            env.PCSD_STATIC_FILES_DIR: pcsd_dir(env.PCSD_STATIC_FILES_DIR_NAME),
            env.HTTPS_PROXY: None,
            env.NO_PROXY: None,
            "has_errors": False,
        }
        if specific_env_values is None:
            specific_env_values = {}

        self.assertEqual(
            env.prepare_env(environ or {}, self.logger),
            env.Env(
                **{
                    **default_env_values,
                    **specific_env_values,
                }
            )
        )
        self.assertEqual(self.logger.errors, errors or [])
        self.assertEqual(self.logger.warnings, warnings or [])

    def test_nothing_in_environ(self):
        self.assert_environ_prdoduces_modified_pcsd_env()

    def test_many_valid_environment_changes(self):
        pcsd_dir = partial(join_path, env.PCSD_LOCAL_DIR)
        environ = {
            env.PCSD_PORT: "1234",
            env.PCSD_SSL_CIPHERS: "DEFAULT:!3DES:@STRENGTH",
            env.PCSD_SSL_OPTIONS: "OP_NO_SSLv2",
            env.PCSD_BIND_ADDR: "abc",
            env.NOTIFY_SOCKET: "xyz",
            env.PCSD_DEBUG: "true",
            env.DISABLE_GUI: "true",
            env.PCSD_SESSION_LIFETIME: 10,
            env.PCSD_DEV: "true",
            env.HTTPS_PROXY: "proxy",
            env.NO_PROXY: "yes",
        }
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ=environ,
            specific_env_values={
                env.PCSD_PORT: environ[env.PCSD_PORT],
                env.PCSD_SSL_CIPHERS: environ[env.PCSD_SSL_CIPHERS],
                env.PCSD_SSL_OPTIONS: OP_NO_SSLv2,
                env.PCSD_BIND_ADDR: {environ[env.PCSD_BIND_ADDR]},
                env.NOTIFY_SOCKET: environ[env.NOTIFY_SOCKET],
                env.PCSD_DEBUG: True,
                env.DISABLE_GUI: True,
                env.PCSD_SESSION_LIFETIME: environ[env.PCSD_SESSION_LIFETIME],
                env.GEM_HOME: pcsd_dir(settings.pcsd_gem_path),
                env.PCSD_CMDLINE_ENTRY: pcsd_dir(
                    env.PCSD_CMDLINE_ENTRY_RB_SCRIPT
                ),
                env.PCSD_STATIC_FILES_DIR: pcsd_dir(
                    env.PCSD_STATIC_FILES_DIR_NAME
                ),
                env.HTTPS_PROXY: environ[env.HTTPS_PROXY],
                env.NO_PROXY: environ[env.NO_PROXY],
            },
        )

    def test_report_invalid_ssl_ciphers(self):
        environ = {env.PCSD_SSL_CIPHERS: "invalid"}
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ,
            specific_env_values={**environ, "has_errors": True},
            errors=["Invalid ciphers: '('No cipher can be selected.',)'"]
        )

    def test_report_invalid_ssl_options(self):
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ={env.PCSD_SSL_OPTIONS: "invalid"},
            specific_env_values={env.PCSD_SSL_OPTIONS: 0, "has_errors": True},
            errors=["Unknown SSL option 'invalid'"]
        )

    def test_report_invalid_ssl_options_warning(self):
        env.settings.default_ssl_options = "invalid"
        self.assert_environ_prdoduces_modified_pcsd_env(
            specific_env_values={env.PCSD_SSL_OPTIONS: 0},
            warnings=["Unknown SSL option 'invalid'"]
        )

    def test_empty_bind_addresses(self):
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ={env.PCSD_BIND_ADDR: " "},
            specific_env_values={env.PCSD_BIND_ADDR: {""}},
        )

    def test_invalid_bind_addresses(self):
        self.socket.gaierror = Exception
        self.socket.getaddrinfo = mock.Mock(side_effect=self.socket.gaierror)
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ={env.PCSD_BIND_ADDR: "invalid"},
            specific_env_values={
                env.PCSD_BIND_ADDR: {"invalid"},
                "has_errors": True
            },
            errors=["Invalid bind address 'invalid': ''"]
        )

    def test_no_disable_gui_explicitly(self):
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ={env.DISABLE_GUI: "false"},
        )

    def test_debug_explicitly(self):
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ={env.PCSD_DEBUG: "true"},
            specific_env_values={env.PCSD_DEBUG: True}
        )

    def test_no_debug_explicitly(self):
        self.assert_environ_prdoduces_modified_pcsd_env(
            {env.PCSD_DEBUG: "false"}
        )

    def test_errors_on_missing_paths(self):
        self.path_exists.return_value = False
        pcsd_dir = partial(join_path, settings.pcsd_exec_location)
        self.assert_environ_prdoduces_modified_pcsd_env(
            specific_env_values={"has_errors": True},
            errors=[
                f"Ruby gem location '{pcsd_dir(settings.pcsd_gem_path)}'"
                    " does not exist"
                ,
                "Ruby handlers entrypoint"
                    f" '{pcsd_dir(env.PCSD_CMDLINE_ENTRY_RB_SCRIPT)}'"
                    " does not exist"
                ,
                "Directory with web UI assets"
                    f" '{pcsd_dir(env.PCSD_STATIC_FILES_DIR_NAME)}'"
                    " does not exist"
                ,
            ]
        )

    def test_errors_on_missing_paths_disabled_gui(self):
        self.path_exists.return_value = False
        pcsd_dir = partial(join_path, settings.pcsd_exec_location)
        self.assert_environ_prdoduces_modified_pcsd_env(
            environ={env.DISABLE_GUI: "true"},
            specific_env_values={env.DISABLE_GUI: True, "has_errors": True},
            errors=[
                f"Ruby gem location '{pcsd_dir(settings.pcsd_gem_path)}'"
                    " does not exist"
                ,
                "Ruby handlers entrypoint"
                    f" '{pcsd_dir(env.PCSD_CMDLINE_ENTRY_RB_SCRIPT)}'"
                    " does not exist"
                ,
            ]
        )
