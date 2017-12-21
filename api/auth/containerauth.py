"""
Purpose of this module is to define all the permissions checker decorators for the ContainerHandler classes.
"""
from copy import deepcopy
from . import _get_access, check_phi, INTEGER_PERMISSIONS
from .. import config
log = config.log


def default_container(handler, container=None, target_parent_container=None):
    """
    This is the default permissions checker generator.
    The resulting permissions checker modifies the exec_op method by checking the user permissions
    on the container before actually executing this method.
    """
    def g(exec_op):
        def f(method, _id=None, payload=None, unset_payload=None, recursive=False, r_payload=None, projection=None, replace_metadata=False, phi=False):
            additional_error_msg = None
            if method == 'GET' and container.get('public', False):
                has_access = True
            elif method == 'GET':
                has_access = _get_access(handler.uid, container) >= INTEGER_PERMISSIONS['ro']
            elif method == 'POST':
                required_perm = 'rw'
                if target_parent_container.get('cont_name') == 'group':
                    # Create project on group, require admin
                    required_perm = 'admin'
                has_access = _get_access(handler.uid, target_parent_container) >= INTEGER_PERMISSIONS[required_perm]
            elif method == 'DELETE':
                required_perm = 'rw'
                if container.get('has_children'):
                    # If the container has children or files, admin is required to delete
                    required_perm = 'admin'
                    additional_error_msg = 'Container is not empty.'
                if target_parent_container:
                    has_access = _get_access(handler.uid, target_parent_container) >= INTEGER_PERMISSIONS[required_perm]
                else:
                    has_access = _get_access(handler.uid, container) >= INTEGER_PERMISSIONS[required_perm]
            elif method == 'PUT' and target_parent_container is not None:
                has_access = (
                    _get_access(handler.uid, container) >= INTEGER_PERMISSIONS['admin'] and
                    _get_access(handler.uid, target_parent_container) >= INTEGER_PERMISSIONS['admin']
                )
            elif method == 'PUT' and target_parent_container is None:
                required_perm = 'rw'
                has_access = _get_access(handler.uid, container) >= INTEGER_PERMISSIONS[required_perm]
            else:
                has_access = False

            if method == 'GET' and phi:
                if not check_phi(handler.uid, container):
                    handler.abort(403, "User not authorized to view PHI fields on the container.")

            if has_access:
                return exec_op(method, _id=_id, payload=payload, unset_payload=unset_payload, recursive=recursive, r_payload=r_payload, replace_metadata=replace_metadata, projection=projection)
            else:
                error_msg = 'user not authorized to perform a {} operation on the container.'.format(method)
                if additional_error_msg:
                    error_msg += ' '+additional_error_msg
                handler.abort(403, error_msg)
        return f
    return g


def collection_permissions(handler, container=None, _=None):
    """
    Collections don't have a parent_container, catch param from generic call with _.
    Permissions are checked on the collection itself or not at all if the collection is new.
    """
    def g(exec_op):
        def f(method, _id=None, payload = None, projection=None, phi=False):
            if method == 'GET' and container.get('public', False):
                has_access = True
            elif method == 'GET':
                has_access = _get_access(handler.uid, container) >= INTEGER_PERMISSIONS['ro']
            elif method == 'DELETE':
                has_access = _get_access(handler.uid, container) >= INTEGER_PERMISSIONS['admin']
            elif method == 'POST':
                has_access = True
            elif method == 'PUT':
                has_access = _get_access(handler.uid, container) >= INTEGER_PERMISSIONS['rw']
            else:
                has_access = False

            if method == 'GET' and phi:
                if not check_phi(handler.uid, container):
                    handler.abort(403, "User not authorized to view PHI fields.")

            if has_access:
                return exec_op(method, _id=_id, payload=payload, projection=projection)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the container'.format(method))
        return f
    return g


def default_referer(handler, parent_container=None):
    def g(exec_op):
        def f(method, _id=None, payload=None, projection = None, phi=False):
            access = _get_access(handler.uid, parent_container)
            if method == 'GET' and parent_container.get('public', False):
                has_access = True
            elif method == 'GET':
                has_access = access >= INTEGER_PERMISSIONS['ro']
            elif method in ['POST', 'PUT', 'DELETE']:
                has_access = access >= INTEGER_PERMISSIONS['rw']
            else:
                has_access = False 

            if method == 'GET' and phi:
                if not check_phi(handler.uid, parent_container):
                    handler.abort(403, "User not authorized to view PHI fields.")

            if has_access:
                return exec_op(method, _id=_id, payload=payload, projection=projection)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on parent container'.format(method))
        return f
    return g


def public_request(handler, container=None):
    """
    For public requests we allow only GET operations on containers marked as public.
    """
    def g(exec_op):
        def f(method, _id=None, payload = None, phi=False, projection=None):
            if phi:
                handler.abort(403, "Must be logged in to view PHI fields.")
            if method == 'GET' and container.get('public', False):
                return exec_op(method, _id, payload=payload, projection=projection)
            else:
                handler.abort(403, 'not authorized to perform a {} operation on this container'.format(method))
        return f
    return g

def list_permission_checker(handler):
    def g(exec_op):
        def f(method, query=None, user=None, public=False, projection=None, phi=False):
            if user and (user['_id'] != handler.uid):
                handler.abort(403, 'User ' + handler.uid + ' may not see the Projects of User ' + user['_id'])
            query['permissions'] = {'$elemMatch': {'_id': handler.uid}}
            if handler.is_true('public'):
                query['$or'] = [{'public': True}, {'permissions': query.pop('permissions')}]
            if phi:
                temp_query = deepcopy(query)
                temp_query['permissions'] = {'$elemMatch': {'_id': handler.uid, 'phi-access': False}}
                log.debug(temp_query)
                log.debug(query)
                not_allowed = exec_op(method, query=temp_query, user=user, public=public, projection=projection)
                if not_allowed:
                    handler.abort(403, "User does not have PHI access to one or more elements")

            return exec_op(method, query=query, user=user, public=public, projection=projection)
        return f
    return g


def list_public_request(exec_op):
    def f(method, query=None, user=None, public=False, projection=None, phi=False): # pylint: disable=unused-argument
        if public:
            query['public'] = True
        return exec_op(method, query=query, user=user, public=public, projection=projection)
    return f

