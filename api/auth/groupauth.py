from . import _get_access, INTEGER_ROLES
from ..request import get_current_request


def default(handler, group=None):
    def g(exec_op):
        def f(method, _id=None, query=None, payload=None, projection=None):
            if handler.superuser_request:
                pass
            elif handler.public_request:
                handler.abort(400, 'public request is not valid')
            elif method in ['DELETE', 'POST']:
                handler.abort(403, 'not allowed to perform operation')
            elif _get_access(handler.uid, handler.user_site, group) >= INTEGER_ROLES['admin']:
                pass
            elif method == 'GET' and _get_access(handler.uid, handler.user_site, group) >= INTEGER_ROLES['ro']:
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
                if uid != handler.uid and not handler.superuser_request:
                    handler.abort(403, 'User ' + handler.uid + ' may not see the Groups of User ' + uid)
                query = query or {}
                query['roles._id'] = uid
                projection = projection or {}
                projection['roles.$'] = 1
            else:
                if not handler.superuser_request:
                    query = query or {}
                    projection = projection or {}
                    if handler.is_true('admin'):
                        query['roles'] = {'$elemMatch': {'_id': handler.uid, 'access': 'admin'}}
                    else:
                        query['roles._id'] = handler.uid
            request = get_current_request()
            request.logger.debug(query)
            request.logger.debug(projection)
            return exec_op(method, query=query, projection=projection)
        return f
    return g
