from . import _get_access, INTEGER_PERMISSIONS
from .. import config

log = config.log


def default(handler, group=None):
    def g(exec_op):
        def f(method, _id=None, query=None, payload=None, projection=None):
            if handler.superuser_request:
                pass
            elif handler.public_request:
                handler.abort(400, 'public request is not valid')
            elif handler.user_is_admin:
                pass
            elif method in ['DELETE', 'POST']:
                handler.abort(403, 'not allowed to perform operation')
            elif _get_access(handler.uid, group) >= INTEGER_PERMISSIONS['admin']:
                pass
            elif method == 'GET' and _get_access(handler.uid, group) >= INTEGER_PERMISSIONS['no-phi-ro']:
                pass
            else:
                handler.abort(403, 'not allowed to perform operation')
            return exec_op(method, _id=_id, query=query, payload=payload, projection=projection)
        return f
    return g

def list_permission_checker(handler, uid=None):
    def g(exec_op):
        def f(method, query=None, projection=None):
            if uid is not None:
                if uid != handler.uid and not handler.superuser_request and not handler.user_is_admin:
                    handler.abort(403, 'User ' + handler.uid + ' may not see the Groups of User ' + uid)
                query = query or {}
                query['permissions._id'] = uid
                projection = projection or {}
                projection['permissions.$'] = 1
            else:
                if not handler.superuser_request and not handler.user_is_admin:
                    query = query or {}
                    projection = projection or {}
                    if handler.is_true('admin'):
                        query['permissions'] = {'$elemMatch': {'_id': handler.uid, 'access': 'admin'}}
                    else:
                        query['permissions._id'] = handler.uid
            log.debug(query)
            log.debug(projection)
            return exec_op(method, query=query, projection=projection)
        return f
    return g
