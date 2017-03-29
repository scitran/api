import json
import time
import logging
import pytest

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)


@pytest.fixture(scope='module')
def module_state(session_state, module_data_builder):
    builder = module_data_builder
    return attrdict.AttrDict(
        group_1       = builder.create_group(_id='test-group-1'),
        project_1     = builder.create_project(label='test-project-1'),
        session_1     = builder.create_session(label='test-session-1'),
        acquisition_1 = builder.create_acquisition(label='test-acquisition-1'),

        group_2       = session_state.group,
        project_2     = session_state.project,
        session_2     = session_state.session,
        acquisition_2 = session_state.acquisition,
    )


def test_switching_project_between_groups(module_state, as_admin):
    data = module_state

    r = as_admin.get('/projects/' + data.project_1)
    assert r.ok
    assert r.json()['group'] == data.group_1

    r = as_admin.put('/projects/' + data.project_1, json={'group': data.group_2})
    assert r.ok

    r = as_admin.get('/projects/' + data.project_1)
    assert r.ok
    assert r.json()['group'] == data.group_2


def test_switching_session_between_projects(function_data_builder, as_admin):
    builder = function_data_builder
    project_1 = builder.create_project(label='test-project-1')
    project_2 = builder.create_project(label='test-project-2')
    session = builder.create_session(project=project_1, label='test-session')

    r = as_admin.put('/sessions/' + session, json={'project': project_2})
    assert r.ok

    r = as_admin.get('/sessions/' + session)
    assert r.ok
    assert r.json()['project'] == project_2


def test_switching_acquisition_between_projects(with_two_groups, data_builder, as_user):
    data = with_two_groups

    project_id = data_builder.create_project(data.group_1)
    session_1_id = data_builder.create_session(project_id)
    session_2_id = data_builder.create_session(project_id)
    acquisition_id = data_builder.create_acquisition(session_1_id)

    payload = json.dumps({'session': session_2_id})
    r = as_user.put('/acquisitions/' + acquisition_id, data=payload)
    assert r.ok

    r = as_user.get('/acquisitions/' + acquisition_id)
    assert r.ok and json.loads(r.content)['session'] == session_2_id

    data_builder.delete_acquisition(acquisition_id)
    data_builder.delete_session(session_1_id)
    data_builder.delete_session(session_2_id)
    data_builder.delete_project(project_id)


def test_project_template(with_hierarchy, data_builder, as_user):
    data = with_hierarchy

    # create template for the project
    r = as_user.post('/projects/' + data.project + '/template', json={
        'session': { 'subject': { 'code' : '^testing' } },
        'acquisitions': [{ 'label': '_testing$', 'minimum': 2 }]
    })
    assert r.ok
    assert r.json()['modified'] == 1

    # test non-compliant session (wrong subject.code and #acquisitions)
    r = as_user.get('/sessions/' + data.session)
    assert r.ok
    assert r.json()['project_has_template'] == True
    assert r.json()['satisfies_template'] == False

    # make session compliant and test it
    r = as_user.put('/sessions/' + data.session, json={
        'subject': { 'code': 'testing' }
    })
    assert r.ok
    acquisition_id = data_builder.create_acquisition(data.session)

    r = as_user.get('/sessions/' + data.session)
    assert r.ok
    assert r.json()['satisfies_template'] == True

    # make session non-compliant again and test it
    r = as_user.put('/sessions/' + data.session, json={
        'subject': { 'code': 'invalid' }
    })
    assert r.ok

    r = as_user.get('/sessions/' + data.session)
    assert r.ok
    assert r.json()['satisfies_template'] == False

    data_builder.delete_acquisition(acquisition_id)

    # delete project template
    r = as_user.delete('/projects/' + data.project + '/template')
    assert r.ok


def test_get_all_containers(with_hierarchy, as_public):
    data = with_hierarchy

    # get all projects w/ info=true
    r = as_public.get('/projects', params={'info': 'true'})
    assert r.ok

    # get all projects w/ counts=true
    r = as_public.get('/projects', params={'counts': 'true'})
    assert r.ok
    assert all('session_count' in proj for proj in r.json())

    # get all sessions for project w/ measurements=true and stats=true
    r = as_public.get('/projects/' + data.project + '/sessions', params={
        'measurements': 'true',
        'stats': 'true'
    })
    assert r.ok


def test_get_all_for_user(as_user, as_public):
    r = as_user.get('/users/self')
    user_id = r.json()['_id']

    # try to get containers for user w/o logging in
    r = as_public.get('/users/' + user_id + '/sessions')
    assert r.status_code == 403

    # get containers for user
    r = as_user.get('/users/' + user_id + '/sessions')
    assert r.ok


def test_get_container(with_hierarchy, as_user, as_public):
    data = with_hierarchy

    # NOTE cannot reach APIStorageException - wanted to cover 400 error w/ invalid oid
    # but then realized that api.py's cid regex makes this an invalid route resulting in 404

    # try to get container w/ invalid object id
    # r = as_user.get('/projects/test')
    # assert r.status_code == 400

    # try to get container w/ nonexistent object id
    r = as_public.get('/projects/000000000000000000000000')
    assert r.status_code == 404

    # get container
    r = as_public.get('/projects/' + data.project)
    assert r.ok

    # get container w/ ?paths=true
    r = as_user.post('/projects/' + data.project + '/files', files={
        'file': ('test.csv', 'header\nrow1\n'),
        'metadata': ('', json.dumps({'name': 'test.csv', 'type': 'csv'}))
    })
    assert r.ok

    r = as_public.get('/projects/' + data.project, params={'paths': 'true'})
    assert r.ok
    assert all('path' in f for f in r.json()['files'])

    # get container w/ ?join=origin
    r = as_public.get('/projects/' + data.project, params={'join': 'origin'})
    assert r.ok
    assert 'join-origin' in r.json()


def test_get_session_jobs(with_hierarchy, with_gear, as_user):
    data = with_hierarchy
    gear = with_gear

    # get session jobs w/ analysis and job
    r = as_user.post('/sessions/' + data.session + '/analyses', params={'job': 'true'}, json={
        'analysis': {'label': 'test analysis'},
        'job': {
            'gear_id': gear,
            'inputs': {
                'dicom': {
                    'type': 'acquisition',
                    'id': data.acquisition,
                    'name': 'test.dcm'
                }
            }
        }
    })
    assert r.ok

    r = as_user.get('/sessions/' + data.session + '/jobs', params={'join': 'containers'})
    assert r.ok


def test_post_container(with_hierarchy, as_user):
    data = with_hierarchy

    # create project w/ param inherit=true
    r = as_user.post('/projects', params={'inherit': 'true'}, json={
        'group': data.group,
        'label': 'test-inheritance-project'
    })
    assert r.ok
    as_user.delete('/projects/' + r.json()['_id'])

    # create session w/ timestamp
    r = as_user.post('/sessions', json={
        'project': data.project,
        'label': 'test-timestamp-session',
        'timestamp': '1979-01-01T00:00:00+00:00'
    })
    assert r.ok
    as_user.delete('/sessions/' + r.json()['_id'])


def test_put_container(with_hierarchy, as_user):
    data = with_hierarchy

    # update session w/ timestamp
    r = as_user.put('/sessions/' + data.session, json={
        'timestamp': '1979-01-01T00:00:00+00:00'
    })
    assert r.ok

    # update subject w/ oid
    r = as_user.put('/sessions/' + data.session, json={
        'subject': {'_id': '000000000000000000000000'}
    })
    assert r.ok
