"""
Purpose of this module is to define all the permissions checker decorators for the ContainerHandler classes.
"""

from . import _get_access, INTEGER_ROLES

def default_container(handler, container=None, target_parent_container=None):
    """
    This is the default permissions checker generator.
    The resulting permissions checker modifies the exec_op method by checking the user permissions
    on the container before actually executing this method.
    """
    def g(exec_op):
        def f(method, _id=None, payload=None, recursive=False, r_payload=None, replace_metadata=False):
            projection = None
            if method == 'GET' and container.get('public', False):
                has_access = True
            elif method == 'GET':
                has_access = True
                if not _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES['ro']:
                    projection = {
                        'subject.firstname': 0,
                        'subject.lastname' : 0
                    }
            elif method == 'POST':
                has_access = _get_access(handler.uid, handler.user_site, target_parent_container) >= INTEGER_ROLES['admin']
            elif method == 'DELETE':
                if target_parent_container:
                    has_access = _get_access(handler.uid, handler.user_site, target_parent_container) >= INTEGER_ROLES['admin']
                else:
                    has_access = _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES['admin']
            elif method == 'PUT' and target_parent_container is not None:
                has_access = (
                    _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES['admin'] and
                    _get_access(handler.uid, handler.user_site, target_parent_container) >= INTEGER_ROLES['admin']
                )
            elif method == 'PUT' and target_parent_container is None:
                required_perm = 'rw'
                if set(['archived','public']).intersection(payload.keys()):
                    required_perm = 'admin'
                has_access = _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES[required_perm]
            else:
                has_access = False

            if has_access and projection:
                return exec_op(method, _id=_id, payload=payload, projection=projection)
            if has_access and recursive:
                return exec_op(method, _id=_id, payload=payload, recursive=recursive, r_payload=r_payload, replace_metadata=replace_metadata)
            elif has_access:
                return exec_op(method, _id=_id, payload=payload, replace_metadata=replace_metadata)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the container'.format(method))
        return f
    return g


def collection_permissions(handler, container=None, _=None):
    """
    Collections don't have a parent_container, catch param from generic call with _.
    Permissions are checked on the collection itself or not at all if the collection is new.
    """
    def g(exec_op):
        def f(method, _id=None, payload = None):
            if method == 'GET' and container.get('public', False):
                has_access = True
            elif method == 'GET':
                has_access = _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES['ro']
            elif method == 'DELETE':
                has_access = _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES['admin']
            elif method == 'POST':
                has_access = True
            elif method == 'PUT':
                has_access = _get_access(handler.uid, handler.user_site, container) >= INTEGER_ROLES['rw']
            else:
                has_access = False

            if has_access:
                return exec_op(method, _id=_id, payload=payload)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the container'.format(method))
        return f
    return g



def public_request(handler, container=None):
    """
    For public requests we allow only GET operations on containers marked as public.
    """
    def g(exec_op):
        def f(method, _id=None, payload = None):
            if method == 'GET' and container.get('public', False):
                return exec_op(method, _id, payload)
            else:
                handler.abort(403, 'not authorized to perform a {} operation on this container'.format(method))
        return f
    return g

def list_permission_checker(handler):
    def g(exec_op):
        def f(method, query=None, user=None, public=False, projection=None):
            handler_site = handler.user_site
            if user and (user['_id'] != handler.uid or user['site'] != handler_site):
                handler.abort(403, 'User ' + handler.uid + ' may not see the Projects of User ' + user['_id'])
            query['permissions'] = {'$elemMatch': {'_id': handler.uid, 'site': handler.user_site}}
            if handler.is_true('public'):
                query['$or'] = [{'public': True}, {'permissions': query.pop('permissions')}]
            return exec_op(method, query=query, user=user, public=public, projection=projection)
        return f
    return g


def list_public_request(exec_op):
    def f(method, query=None, user=None, public=False, projection=None):
        if public:
            query['public'] = True
        return exec_op(method, query=query, user=user, public=public, projection=projection)
    return f
