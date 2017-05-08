def test_login(as_public):
    # try to login w/o code/auth_type
    r = as_public.post('/login', json={})
    assert r.status_int == 400

    # try to login w/ invalid auth_type
    r = as_public.post('/login', json={'code': 'test', 'auth_type': 'test'})
    assert r.status_int == 400


def test_authenticate_user_token(as_public):
    # try to access api w/ invalid session token
    r = as_public.get('', headers={'Authorization': 'test'})
    assert r.status_int == 401
