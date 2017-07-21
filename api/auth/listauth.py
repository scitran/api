"""
Purpose of this module is to define all the permissions checker decorators for the ListHandler classes.

"""

import sys

from .. import config
from . import _get_access, INTEGER_PERMISSIONS

log = config.log


def default_sublist(handler, container):
    """
    This is the default permissions checker generator.
    The resulting permissions checker modifies the exec_op method by checking the user permissions
    on the container before actually executing this method.
    """
    access = _get_access(handler.uid, container)
    def g(exec_op):
        def f(method, _id, query_params=None, payload=None, exclude_params=None):
            if method == 'GET' and container.get('public', False):
                min_access = -1
            elif method == 'GET':
                min_access = INTEGER_PERMISSIONS['no-phi-ro']
            elif method in ['POST', 'PUT', 'DELETE']:
                min_access = INTEGER_PERMISSIONS['rw']
            else:
                min_access = sys.maxint

            if access >= min_access:
                return exec_op(method, _id, query_params, payload, exclude_params)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the list'.format(method))
        return f
    return g

def group_permissions_sublist(handler, container):
    """
    This is the customized permissions checker for group permissions operations.
    """
    access = _get_access(handler.uid, container)
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            if method in ['GET', 'DELETE']  and query_params.get('_id') == handler.uid:
                return exec_op(method, _id, query_params, payload, exclude_params)
            elif access >= INTEGER_PERMISSIONS['admin']:
                return exec_op(method, _id, query_params, payload, exclude_params)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the list'.format(method))
        return f
    return g

def group_tags_sublist(handler, container):
    """
    This is the customized permissions checker for tags operations.
    """
    access = _get_access(handler.uid, container)
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            if method == 'GET'  and access >= INTEGER_PERMISSIONS['no-phi-ro']:
                return exec_op(method, _id, query_params, payload, exclude_params)
            elif access >= INTEGER_PERMISSIONS['rw']:
                return exec_op(method, _id, query_params, payload, exclude_params)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the list'.format(method))
        return f
    return g

def permissions_sublist(handler, container):
    """
    the customized permissions checker for permissions operations.
    """
    access = _get_access(handler.uid, container)
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            log.debug(query_params)
            if method in ['GET', 'DELETE']  and query_params.get('_id') == handler.uid:
                return exec_op(method, _id, query_params, payload, exclude_params)
            elif access >= INTEGER_PERMISSIONS['admin']:
                return exec_op(method, _id, query_params, payload, exclude_params)
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the list'.format(method))
        return f
    return g

def notes_sublist(handler, container):
    """
    permissions checker for notes_sublist
    """
    access = _get_access(handler.uid, container)
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            if access >= INTEGER_PERMISSIONS['admin']:
                pass
            elif method == 'POST' and access >= INTEGER_PERMISSIONS['rw'] and payload['user'] == handler.uid:
                pass
            elif method == 'GET' and (access >= INTEGER_PERMISSIONS['no-phi-ro'] or container.get('public')):
                pass
            elif method in ['GET', 'DELETE', 'PUT'] and container['notes'][0]['user'] == handler.uid:
                pass
            else:
                handler.abort(403, 'user not authorized to perform a {} operation on the list'.format(method))
            return exec_op(method, _id, query_params, payload, exclude_params)
        return f
    return g

def public_request(handler, container):
    """
    For public requests we allow only GET operations on containers marked as public.
    """
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            if method == 'GET' and container.get('public', False):
                return exec_op(method, _id, query_params, payload, exclude_params)
            else:
                handler.abort(403, 'not authorized to perform a {} operation on this container'.format(method))
        return f
    return g
