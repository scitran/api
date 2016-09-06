from .. import config

log = config.log


def default(handler, user=None):
    def g(exec_op):
        def f(method, _id=None, query=None, payload=None, projection=None):
            if handler.public_request:
                handler.abort(403, 'public request is not authorized')
            elif handler.superuser_request and not (method == 'DELETE' and _id == handler.uid):
                pass
            elif method == 'PUT' and handler.uid == _id:
                if 'root' in payload and payload['root'] != user['root']:
                    handler.abort(400, 'user cannot alter own superuser privilege')
                elif 'disabled' in payload and payload['disabled'] != user.get('disabled'):
                    handler.abort(400, 'user cannot alter own disabled status')
                else:
                    pass
            elif method == 'POST' and not handler.superuser_request:
                handler.abort(403, 'only superuser are allowed to create users')
            elif method == 'POST' and handler.superuser_request:
                pass
            elif method == 'GET' and _id == handler.uid:
                pass
            else:
                handler.abort(403, 'not allowed to perform operation')
            return exec_op(method, _id=_id, query=query, payload=payload, projection=projection)
        return f
    return g

def list_permission_checker(handler):
    def g(exec_op):
        def f(method, query=None, projection=None):
            if handler.public_request:
                handler.abort(403, 'public request is not authorized')
            return exec_op(method, query=query, projection=projection)
        return f
    return g
