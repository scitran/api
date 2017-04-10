def test_collections(data_builder, as_admin):
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    # create collection
    r = as_admin.post('/collections', json={
        'label': 'SciTran/Testing',
        'public': True
    })
    assert r.ok
    collection = r.json()['_id']

    # get all collections w/ stats=true
    r = as_admin.get('/collections', params={'stats': 'true'})
    assert r.ok
    assert all('session_count' in coll for coll in r.json())

    # get collection
    r = as_admin.get('/collections/' + collection)
    assert r.ok

    # add session to collection
    r = as_admin.put('/collections/' + collection, json={
        'contents': {
            'operation': 'add',
            'nodes': [
                {'level': 'session', '_id': session}
            ],
        }
    })
    assert r.ok

    # test if collection is listed at acquisition
    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok
    assert collection in r.json()['collections']

    # delete collection
    r = as_admin.delete('/collections/' + collection)
    assert r.ok

    # try to get deleted collection
    r = as_admin.get('/collections/' + collection)
    assert r.status_code == 404

    # test if collection is listed at acquisition
    r = as_admin.get('/acquisitions/' + acquisition)
    assert collection not in r.json()['collections']
