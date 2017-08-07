def default(handler, user=None):
    def g(exec_op):
        def f(method, _id=None, query=None, payload=None, projection=None):
            if handler.public_request:
                handler.abort(403, 'public request is not authorized') # cover 100
            elif handler.superuser_request and not (method == 'DELETE' and _id == handler.uid):
                pass
            elif handler.user_is_admin and (method == 'DELETE' and not _id == handler.uid):
                pass
            elif method == 'PUT' and handler.uid == _id:
                if 'root' in payload and payload['root'] != user['root']: # cover 100
                    handler.abort(400, 'user cannot alter own admin privilege')
                elif 'disabled' in payload and payload['disabled'] != user.get('disabled'): # cover 100
                    handler.abort(400, 'user cannot alter own disabled status')
                else: # cover 100
                    pass
            elif method == 'PUT' and handler.user_is_admin:
                pass
            elif method == 'POST' and not handler.superuser_request and not handler.user_is_admin:
                handler.abort(403, 'only admins are allowed to create users') # cover 100
            elif method == 'POST' and (handler.superuser_request or handler.user_is_admin):
                pass
            elif method == 'GET':
                pass
            else:
                handler.abort(403, 'not allowed to perform operation') # cover 100
            return exec_op(method, _id=_id, query=query, payload=payload, projection=projection)
        return f
    return g

def list_permission_checker(handler):
    def g(exec_op):
        def f(method, query=None, projection=None):
            if handler.public_request:
                handler.abort(403, 'public request is not authorized') # cover 100
            return exec_op(method, query=query, projection=projection)
        return f
    return g
