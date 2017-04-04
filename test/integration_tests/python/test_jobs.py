import copy


def test_jobs_access(as_user):
    r = as_user.get('/jobs')
    assert r.status_code == 403

    r = as_user.get('/jobs/next')
    assert r.status_code == 403

    r = as_user.get('/jobs/stats')
    assert r.status_code == 403

    r = as_user.post('/jobs/reap')
    assert r.status_code == 403

    r = as_user.get('/jobs/test-job')
    assert r.status_code == 403

    r = as_user.get('/jobs/test-job/config.json')
    assert r.status_code == 403


def test_jobs(data_builder, as_admin, as_root):
    gear = data_builder.create_gear()
    invalid_gear = data_builder.create_gear(gear={'custom': {'flywheel': {'invalid': True}}})
    acquisition = data_builder.create_acquisition()

    job1 = {
        'gear_id': gear,
        'inputs': {
            'dicom': {
                'type': 'acquisition',
                'id': acquisition,
                'name': 'test.zip'
            }
        },
        'config': { 'two-digit multiple of ten': 20 },
        'destination': {
            'type': 'acquisition',
            'id': acquisition
        },
        'tags': [ 'test-tag' ]
    }

    # add job with explicit destination
    r = as_admin.post('/jobs/add', json=job1)
    assert r.ok
    job1_id = r.json()['_id']

    # get job
    r = as_root.get('/jobs/' + job1_id)
    assert r.ok

    # add job log
    r = as_root.post('/jobs/' + job1_id + '/logs', json=[
        { 'fd': 1, 'msg': 'Hello' },
        { 'fd': 2, 'msg': 'World' }
    ])
    assert r.ok

    # get job log
    r = as_admin.get('/jobs/' + job1_id + '/logs')
    assert r.ok
    assert len(r.json()['logs']) == 2

    # get job config
    r = as_root.get('/jobs/' + job1_id + '/config.json')
    assert r.ok

    # try to update job (user may only cancel)
    r = as_admin.put('/jobs/' + job1_id, json={'test': 'invalid'})
    assert r.status_code == 403

    # add job with implicit destination
    job2 = copy.deepcopy(job1)
    del job2['destination']
    r = as_admin.post('/jobs/add', json=job2)
    assert r.ok

    # add job with invalid gear
    job3 = copy.deepcopy(job2)
    job3['gear_id'] = invalid_gear

    r = as_admin.post('/jobs/add', json=job3)
    assert r.status_code == 400

    # get next job - with nonexistent tag
    r = as_root.get('/jobs/next', params={'tags': 'fake-tag'})
    assert r.status_code == 400

    # get next job
    r = as_root.get('/jobs/next', params={'tags': 'test-tag'})
    assert r.ok
    next_job_id = r.json()['id']

    # retry job
    r = as_root.put('/jobs/' + next_job_id, json={'state': 'failed'})
    assert r.ok

    r = as_root.post('/jobs/' + next_job_id + '/retry')
    assert r.ok
