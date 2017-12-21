def test_collections(data_builder, as_admin, as_user):
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    # create collection
    r = as_admin.post('/collections', json={
        'label': 'SciTran/Testing'
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

    # test empty update
    r = as_admin.put('/collections/' + collection, json={})
    assert r.status_code == 400

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


    ###
    #   Test user only sees sessions/acquisitions they have access to
    ###

    project2 = data_builder.create_project()
    session2 = data_builder.create_session(project=project2)
    acquisition2 = data_builder.create_acquisition(session=session2)

    # add session2 to collection
    r = as_admin.put('/collections/' + collection, json={
        'contents': {
            'operation': 'add',
            'nodes': [
                {'level': 'session', '_id': session2}
            ],
        }
    })
    assert r.ok

    # test user cannot access sessions/acquisitions of collection without perms
    r = as_user.get('/collections/' + collection)
    assert r.status_code == 403
    r = as_user.get('/collections/' + collection + '/sessions')
    assert r.status_code == 403
    r = as_user.get('/collections/' + collection + '/acquisitions')
    assert r.status_code == 403


    # add user to collection
    r = as_user.get('/users/self')
    assert r.ok
    uid = r.json()['_id']

    r = as_admin.post('/collections/' + collection + '/permissions', json={'_id': uid, 'access': 'ro', 'phi-access':True})
    assert r.ok

    # test user cannot see sessions or acquisitions
    r = as_user.get('/collections/' + collection + '/sessions')
    assert r.ok
    assert r.json() == []

    r = as_user.get('/collections/' + collection + '/acquisitions')
    assert r.ok
    assert r.json() == []

    # add user to project
    r = as_admin.post('/projects/' + project2 + '/permissions', json={'_id': uid, 'access': 'ro', 'phi-access':True})
    assert r.ok

    # test user can now see some of sessions and acquisitions
    r = as_user.get('/collections/' + collection + '/sessions')
    assert r.ok
    sessions = r.json()
    assert len(sessions) == 1
    assert sessions[0]['_id'] == session2

    r = as_user.get('/collections/' + collection + '/acquisitions')
    assert r.ok
    acquisitions = r.json()
    assert len(acquisitions) == 1
    assert acquisitions[0]['_id'] == acquisition2


    # delete collection
    r = as_admin.delete('/collections/' + collection)
    assert r.ok

    # try to get deleted collection
    r = as_admin.get('/collections/' + collection)
    assert r.status_code == 404

    # test if collection is listed at acquisition
    r = as_admin.get('/acquisitions/' + acquisition)
    assert collection not in r.json()['collections']

def test_collections_phi(data_builder, as_admin, as_user, log_db, as_root,file_form):
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    # Set sitewide phi fields
    r = as_admin.post("/projects/site/phi", json={"fields":["files.info"]})
    assert r.ok

    # create collection
    r = as_admin.post('/collections', json={
        'label': 'SciTran/Testing',
        'public': True
    })
    assert r.ok
    collection = r.json()['_id']

    file_name = 'test_file.txt'

    assert as_admin.post('/collections/' + collection + '/files', files=file_form(file_name)).ok

    # Attempt full replace of info
    file_info = {
        'a': 'b',
        'test': 123,
        'map': {
            'a': 'b'
        },
        'list': [1,2,3]
    }


    r = as_admin.post('/collections/' + collection + '/files/' + file_name + '/info', json={
        'replace': file_info
    })
    assert r.ok


    # Test phi access for list returns with phi access level
    pre_log = log_db.access_log.count({})
    r = as_admin.get('/collections', params={"phi":False})
    assert r.ok
    for collection_ in r.json():
        assert collection_.get('files',[{}])[0].get('info') == None
    assert pre_log == log_db.access_log.count({})
    r = as_admin.get('/collections', params={'phi':True})
    assert r.ok
    for collection_ in r.json():
        assert collection_.get('files',[{}])[0].get('info').get('a') == "b"
    assert pre_log == log_db.access_log.count({}) - len(r.json())

    # Test phi access for individual elements with phi access level
    pre_log = log_db.access_log.count({})
    r = as_admin.get('/collections/' + collection)
    assert r.ok
    assert r.json().get('files',[{}])[0].get('info').get('a') == "b"
    assert pre_log == log_db.access_log.count({}) - 1
    pre_log = log_db.access_log.count({})

    r = as_admin.get('/collections/' + collection, params={'phi':True})
    assert r.ok
    assert r.json().get('files',[{}])[0].get('info').get('a') == "b"
    assert pre_log == log_db.access_log.count({}) - 1


    # Test phi access without phi access
    r = as_admin.put("/collections/" + collection + "/permissions/admin@user.com", json={"phi-access":False})
    assert r.ok
    r = as_admin.get("/collections/" + collection + "/permissions/admin@user.com")
    assert r.ok
    assert r.json().get("phi-access") == False

    pre_log = log_db.access_log.count({})
    r = as_admin.get('/collections', params={"phi":False})
    assert r.ok
    for collection_ in r.json():
        assert collection_.get('files',[{}])[0].get('info') == None
    assert pre_log == log_db.access_log.count({})
    r = as_admin.get('/collections', params={'phi':True})
    assert r.status_code == 403

    # Test phi access for individual elements without phi access level
    pre_log = log_db.access_log.count({})
    r = as_admin.get('/collections/' + collection)
    assert r.ok
    assert r.json().get('files',[{}])[0].get('info') == None
    assert pre_log == log_db.access_log.count({})
    pre_log = log_db.access_log.count({})


    # Test phi access for individual elements without phi access level but with root
    r = as_root.get('/collections/' + collection)
    assert r.ok
    assert r.json().get('files',[{}])[0].get('info').get('a') == "b"
    assert pre_log == log_db.access_log.count({}) - 1


    r = as_admin.delete('/collections/'+ collection)
    assert r.ok
    # Unset sitewide phi fields
    r = as_admin.put("/projects/site/phi", json={"fields":[]})
    assert r.ok
