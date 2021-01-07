from contextlib import contextmanager

from pcs.common.tools import Version
from pcs.lib.cib import acl
from pcs.lib.cib.tools import get_acls


REQUIRED_CIB_VERSION = Version(2, 0, 0)


@contextmanager
def cib_acl_section(env):
    yield get_acls(env.get_cib(REQUIRED_CIB_VERSION))
    env.push_cib()


def create_role(lib_env, role_id, permission_info_list, description):
    """
    Create new acl role.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvirnoment
    role_id -- id of new role which should be created
    permission_info_list -- list of permissons, items of list should be tuples:
        (<read|write|deny>, <xpath|id>, <any string>)
    description -- text description for role
    """
    with cib_acl_section(lib_env) as acl_section:
        if permission_info_list:
            acl.validate_permissions(acl_section, permission_info_list)
        role_el = acl.create_role(acl_section, role_id, description)
        if permission_info_list:
            acl.add_permissions_to_role(role_el, permission_info_list)


def remove_role(lib_env, role_id, autodelete_users_groups=False):
    """
    Remove role with specified id from CIB.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    role_id -- id of role which should be deleted
    autodelete_users_groups -- if True targets and groups which are empty after
        removal will be removed
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.remove_role(acl_section, role_id, autodelete_users_groups)


def assign_role_not_specific(lib_env, role_id, target_or_group_id):
    """
    Assign role with id role_id to target or group with id target_or_group_id.
    Target element has bigger priority so if there are target and group with
    the same id only target element will be affected by this function.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnviroment
    role_id -- id of role which should be assigned to target/group
    target_or_group_id -- id of target/group element
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.assign_role(
            acl_section,
            role_id,
            acl.find_target_or_group(acl_section, target_or_group_id),
        )


def assign_role_to_target(lib_env, role_id, target_id):
    """
    Assign role with id role_id to target with id target_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    role_id -- id of acl_role element which should be assigned to target
    target_id -- id of acl_target element to which role should be assigned
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.assign_role(
            acl_section,
            role_id,
            acl.find_target(acl_section, target_id),
        )


def assign_role_to_group(lib_env, role_id, group_id):
    """
    Assign role with id role_id to group with id group_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    role_id -- id of acl_role element which should be assigned to group
    group_id -- id of acl_group element to which role should be assigned
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.assign_role(
            acl_section,
            role_id,
            acl.find_group(acl_section, group_id),
        )


def unassign_role_not_specific(
    lib_env, role_id, target_or_group_id, autodelete_target_group=False
):
    """
    Unassign role with role_id from target/group with id target_or_group_id.
    Target element has bigger priority so if there are target and group with
    the same id only target element will be affected by this function.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    role_id -- id of role which should be unassigned from target/group
    target_or_group_id -- id of acl_target/acl_group element
    autodelete_target_group -- if True remove target/group element if has no
        more role assigned
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.unassign_role(
            acl.find_target_or_group(acl_section, target_or_group_id),
            role_id,
            autodelete_target_group,
        )


def unassign_role_from_target(
    lib_env, role_id, target_id, autodelete_target=False
):
    """
    Unassign role with role_id from group with id target_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    role_id -- id of role which should be unassigned from target
    target_id -- id of acl_target element
    autodelete_target -- if True remove target element if has no more role
        assigned
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.unassign_role(
            acl.find_target(acl_section, target_id), role_id, autodelete_target
        )


def unassign_role_from_group(
    lib_env, role_id, group_id, autodelete_group=False
):
    """
    Unassign role with role_id from group with id group_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    role_id -- id of role which should be unassigned from group
    group_id -- id of acl_group element
    autodelete_target -- if True remove group element if has no more role
        assigned
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.unassign_role(
            acl.find_group(acl_section, group_id), role_id, autodelete_group
        )


def create_target(lib_env, target_id, role_list):
    """
    Create new target with id target_id and assign roles role_list to it.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    target_id -- id of new target
    role_list -- list of roles to assign to new target
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.assign_all_roles(
            acl_section, role_list, acl.create_target(acl_section, target_id)
        )


def create_group(lib_env, group_id, role_list):
    """
    Create new group with id group_id and assign roles role_list to it.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    group_id -- id of new group
    role_list -- list of roles to assign to new group
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.assign_all_roles(
            acl_section, role_list, acl.create_group(acl_section, group_id)
        )


def remove_target(lib_env, target_id):
    """
    Remove acl_target element with id target_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    target_id -- id of taget which should be removed
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.remove_target(acl_section, target_id)


def remove_group(lib_env, group_id):
    """
    Remove acl_group element with id group_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    group_id -- id of group which should be removed
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.remove_group(acl_section, group_id)


def add_permission(lib_env, role_id, permission_info_list):
    """
    Add permissions do role with id role_id. If role doesn't exist it will be
    created.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvirnoment
    role_id -- id of role
    permission_info_list -- list of permissons, items of list should be tuples:
        (<read|write|deny>, <xpath|id>, <any string>)
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.validate_permissions(acl_section, permission_info_list)
        acl.add_permissions_to_role(
            acl.provide_role(acl_section, role_id), permission_info_list
        )


def remove_permission(lib_env, permission_id):
    """
    Remove permission with id permission_id.
    Raises LibraryError on any failure.

    lib_env -- LibraryEnvironment
    permission_id -- id of permission element which should be removed
    """
    with cib_acl_section(lib_env) as acl_section:
        acl.remove_permission(acl_section, permission_id)


def get_config(lib_env):
    """
    Returns ACL configuration in dictionary. Format of output:
        {
            "target_list": <list of targets>,
            "group_list": <list og groups>,
            "role_list": <list of roles>,
        }

    lib_env -- LibraryEnvironment
    """
    acl_section = get_acls(lib_env.get_cib(REQUIRED_CIB_VERSION))
    return {
        "target_list": acl.get_target_list(acl_section),
        "group_list": acl.get_group_list(acl_section),
        "role_list": acl.get_role_list(acl_section),
    }
