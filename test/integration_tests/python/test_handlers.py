def test_roothandler(as_public):
    r = as_public.get('')
    assert r.ok
    assert '<title>SciTran API</title>' in r.text


def test_schemahandler(as_public):
    r = as_public.get('/schemas/non/existent.json')
    assert r.status_code == 404

    r = as_public.get('/schemas/definitions/user.json')
    assert r.ok
    schema = r.json()
    assert all(attr in schema['definitions'] for attr in ('_id', 'firstname', 'lastname'))
