import os.path

systemctl_binary = "/bin/systemctl"
chkconfig_binary = "/sbin/chkconfig"
service_binary = "/sbin/service"
pacemaker_binaries = "/usr/sbin/"
corosync_binaries = "/usr/sbin/"
corosync_qnet_binaries = "/usr/bin/"
ccs_binaries = "/usr/sbin/"
corosync_conf_dir = "/etc/corosync/"
corosync_conf_file = os.path.join(corosync_conf_dir, "corosync.conf")
corosync_uidgid_dir = os.path.join(corosync_conf_dir, "uidgid.d/")
corosync_qdevice_net_server_certs_dir = os.path.join(
    corosync_conf_dir,
    "qnetd/nssdb"
)
corosync_qdevice_net_client_certs_dir = os.path.join(
    corosync_conf_dir,
    "qdevice/net/nssdb"
)
corosync_qdevice_net_client_ca_file_name = "qnetd-cacert.crt"
corosync_authkey_file = os.path.join(corosync_conf_dir, "authkey")
corosync_log_file = "/var/log/cluster/corosync.log"
pacemaker_authkey_file = "/etc/pacemaker/authkey"
booth_authkey_file_mode = 0o600
cluster_conf_file = "/etc/cluster/cluster.conf"
fence_agent_binaries = "/usr/sbin/"
pengine_binary = "/usr/libexec/pacemaker/pengine"
crmd_binary = "/usr/libexec/pacemaker/crmd"
cib_binary = "/usr/libexec/pacemaker/cib"
stonithd_binary = "/usr/libexec/pacemaker/stonithd"
pcs_version = "0.10.0.1"
crm_report = pacemaker_binaries + "crm_report"
crm_verify = pacemaker_binaries + "crm_verify"
crm_mon_schema = '/usr/share/pacemaker/crm_mon.rng'
agent_metadata_schema = "/usr/share/resource-agents/ra-api-1.dtd"
pcsd_cert_location = "/var/lib/pcsd/pcsd.crt"
pcsd_key_location = "/var/lib/pcsd/pcsd.key"
pcsd_users_conf_location = "/var/lib/pcsd/pcs_users.conf"
pcsd_settings_conf_location = "/var/lib/pcsd/pcs_settings.conf"
pcsd_exec_location = "/usr/lib/pcsd/"
pcsd_log_location = "/var/log/pcsd/pcsd.log"
pcsd_default_port = 2224
cib_dir = "/var/lib/pacemaker/cib/"
pacemaker_uname = "hacluster"
pacemaker_gname = "haclient"
sbd_binary = "/usr/sbin/sbd"
sbd_watchdog_default = "/dev/watchdog"
sbd_config = "/etc/sysconfig/sbd"
# this limit is also mentioned in docs, change there as well
sbd_max_device_num = 3
# message types are also mentioned in docs, change there as well
sbd_message_types = ["test", "reset", "off", "crashdump", "exit", "clear"]
pacemaker_wait_timeout_status = 62
booth_config_dir = "/etc/booth"
booth_binary = "/usr/sbin/booth"
default_request_timeout = 60
pcs_bundled_dir = "/usr/lib/pcs/bundled/"
pcs_bundled_pacakges_dir = os.path.join(pcs_bundled_dir, "packages")

default_ssl_ciphers = "DEFAULT:!RC4:!3DES:@STRENGTH"

# Ssl options are based on default options in python (maybe with some extra
# options). Format here is the same as the PCSD_SSL_OPTIONS environment
# variable format (string with coma as a delimiter).
default_ssl_options = ",".join([
    "OP_NO_COMPRESSION",
    "OP_CIPHER_SERVER_PREFERENCE",
    "OP_SINGLE_DH_USE",
    "OP_SINGLE_ECDH_USE",
    "OP_NO_SSLv2",
    "OP_NO_SSLv3",
    "OP_NO_TLSv1",
    "OP_NO_TLSv1_1",
])
pcsd_gem_path = "vendor/bundle/ruby"
ruby_executable = "/usr/bin/ruby"

gui_session_lifetime_seconds=60 * 60
