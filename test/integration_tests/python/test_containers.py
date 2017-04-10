def test_switching_project_between_groups(data_builder, as_admin):
    group_1 = data_builder.create_group()
    group_2 = data_builder.create_group()
    project = data_builder.create_project(group=group_1)

    r = as_admin.put('/projects/' + project, json={'group': group_2})
    assert r.ok

    r = as_admin.get('/projects/' + project)
    assert r.ok
    assert r.json()['group'] == group_2


def test_switching_session_between_projects(data_builder, as_admin):
    project_1 = data_builder.create_project()
    project_2 = data_builder.create_project()
    session = data_builder.create_session(project=project_1)

    r = as_admin.put('/sessions/' + session, json={'project': project_2})
    assert r.ok

    r = as_admin.get('/sessions/' + session)
    assert r.ok
    assert r.json()['project'] == project_2


def test_switching_acquisition_between_sessions(data_builder, as_admin):
    session_1 = data_builder.create_session()
    session_2 = data_builder.create_session()
    acquisition = data_builder.create_acquisition(session=session_1)

    r = as_admin.put('/acquisitions/' + acquisition, json={'session': session_2})
    assert r.ok

    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok
    assert r.json()['session'] == session_2


def test_project_template(data_builder, file_form, as_admin):
    project = data_builder.create_project()
    session = data_builder.create_session(subject={'code': 'compliant'})
    # NOTE adding acquisition_1 to cover code that's skipping non-matching containers
    acquisition_1 = data_builder.create_acquisition(label='non-compliant')
    acquisition_2 = data_builder.create_acquisition(label='compliant')
    assert as_admin.post('/acquisitions/' + acquisition_2 + '/tags', json={'value': 'compliant'}).ok
    assert as_admin.post('/acquisitions/' + acquisition_2 + '/files', files=file_form('non-compliant.txt')).ok
    assert as_admin.post('/acquisitions/' + acquisition_2 + '/files', files=file_form('compliant1.csv')).ok
    assert as_admin.post('/acquisitions/' + acquisition_2 + '/files', files=file_form('compliant2.csv')).ok

    # test the session before setting the template
    r = as_admin.get('/sessions/' + session)
    assert r.ok
    assert 'project_has_template' not in r.json()

    # create template for the project
    r = as_admin.post('/projects/' + project + '/template', json={
        'session': {'subject': {'code': '^compliant$'}},
        'acquisitions': [{
            'minimum': 1,
            'label': '^compliant$',
            'tags': '^compliant$',
            'files': [{
                'minimum': 2,
                'mimetype': 'text/csv',
            }]
        }]
    })
    assert r.ok
    assert r.json()['modified'] == 1

    # test session compliance
    r = as_admin.get('/sessions/' + session)
    assert r.ok
    assert r.json()['project_has_template']

    def satisfies_template():
        r = as_admin.get('/sessions/' + session)
        assert r.ok
        return r.json()['satisfies_template']

    # test that missing any single requirement breaks compliance
    # session.subject.code
    assert satisfies_template()
    assert as_admin.put('/sessions/' + session, json={'subject': {'code': 'non-compliant'}}).ok
    assert not satisfies_template()
    assert as_admin.put('/sessions/' + session, json={'subject': {'code': 'compliant'}}).ok

    # acquisitions.label
    assert satisfies_template()
    assert as_admin.put('/acquisitions/' + acquisition_2, json={'label': 'non-compliant'}).ok
    assert not satisfies_template()
    assert as_admin.put('/acquisitions/' + acquisition_2, json={'label': 'compliant'}).ok

    # acquisitions.tags
    assert satisfies_template()
    assert as_admin.delete('/acquisitions/' + acquisition_2 + '/tags/compliant').ok
    # TODO figure out why removing the tag does not break compliance
    # assert not satisfies_template()
    assert as_admin.post('/acquisitions/' + acquisition_2 + '/tags', json={'value': 'compliant'}).ok

    # acquisitions.files.minimum
    assert satisfies_template()
    assert as_admin.delete('/acquisitions/' + acquisition_2 + '/files/compliant2.csv').ok
    assert not satisfies_template()
    assert as_admin.post('/acquisitions/' + acquisition_2 + '/files', files=file_form('compliant2.csv')).ok

    # acquisitions.minimum
    assert satisfies_template()
    assert as_admin.delete('/acquisitions/' + acquisition_2)
    assert not satisfies_template()

    # delete project template
    r = as_admin.delete('/projects/' + project + '/template')
    assert r.ok

    r = as_admin.get('/sessions/' + session)
    assert r.ok
    assert 'project_has_template' not in r.json()


def test_get_all_containers(data_builder, as_public):
    project_1 = data_builder.create_project()
    project_2 = data_builder.create_project()
    session = data_builder.create_session(project=project_1)

    # get all projects w/ info=true
    r = as_public.get('/projects', params={'info': 'true'})
    assert r.ok

    # get all projects w/ counts=true
    r = as_public.get('/projects', params={'counts': 'true'})
    assert r.ok
    assert all('session_count' in proj for proj in r.json())

    # get all projects w/ stats=true
    r = as_public.get('/projects', params={'stats': 'true'})
    assert r.ok

    # get all sessions for project w/ measurements=true and stats=true
    r = as_public.get('/projects/' + project_1 + '/sessions', params={
        'measurements': 'true',
        'stats': 'true'
    })
    assert r.ok


def test_get_all_for_user(as_admin, as_public):
    r = as_admin.get('/users/self')
    user_id = r.json()['_id']

    # try to get containers for user w/o logging in
    r = as_public.get('/users/' + user_id + '/sessions')
    assert r.status_code == 403

    # get containers for user
    r = as_admin.get('/users/' + user_id + '/sessions')
    assert r.ok


def test_get_container(data_builder, file_form, as_admin, as_public):
    project = data_builder.create_project()

    # NOTE cannot reach APIStorageException - wanted to cover 400 error w/ invalid oid
    # but then realized that api.py's cid regex makes this an invalid route resulting in 404

    # try to get container w/ invalid object id
    # r = as_admin.get('/projects/test')
    # assert r.status_code == 400

    # try to get container w/ nonexistent object id
    r = as_public.get('/projects/000000000000000000000000')
    assert r.status_code == 404

    # get container
    r = as_public.get('/projects/' + project)
    assert r.ok

    # get container w/ ?paths=true
    r = as_admin.post('/projects/' + project + '/files', files=file_form(
        'one.csv', meta={'name': 'one.csv', 'type': 'csv'}))
    assert r.ok

    r = as_public.get('/projects/' + project, params={'paths': 'true'})
    assert r.ok
    assert all('path' in f for f in r.json()['files'])

    # get container w/ ?join=origin
    r = as_public.get('/projects/' + project, params={'join': 'origin'})
    assert r.ok
    assert 'join-origin' in r.json()


def test_get_session_jobs(data_builder, as_admin):
    gear = data_builder.create_gear()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    # get session jobs w/ analysis and job
    r = as_admin.post('/sessions/' + session + '/analyses', params={'job': 'true'}, json={
        'analysis': {'label': 'test analysis'},
        'job': {
            'gear_id': gear,
            'inputs': {
                'dicom': {
                    'type': 'acquisition',
                    'id': acquisition,
                    'name': 'test.dcm'
                }
            }
        }
    })
    assert r.ok

    r = as_admin.get('/sessions/' + session + '/jobs', params={'join': 'containers'})
    assert r.ok


def test_post_container(data_builder, as_admin):
    group = data_builder.create_group()

    # create project w/ param inherit=true
    r = as_admin.post('/projects', params={'inherit': 'true'}, json={
        'group': group,
        'label': 'test-inheritance-project'
    })
    assert r.ok
    project = r.json()['_id']

    # create session w/ timestamp
    r = as_admin.post('/sessions', json={
        'project': project,
        'label': 'test-timestamp-session',
        'timestamp': '1979-01-01T00:00:00+00:00'
    })
    assert r.ok

    data_builder.delete_group(group, recursive=True)


def test_put_container(data_builder, as_admin):
    session = data_builder.create_session()

    # update session w/ timestamp
    r = as_admin.put('/sessions/' + session, json={
        'timestamp': '1979-01-01T00:00:00+00:00'
    })
    assert r.ok

    # update subject w/ oid
    r = as_admin.put('/sessions/' + session, json={
        'subject': {'_id': '000000000000000000000000'}
    })
    assert r.ok
