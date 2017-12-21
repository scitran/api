import copy

import bson
import datetime

def test_jobs_access(as_user):
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


def test_jobs(data_builder, default_payload, as_public, as_user, as_admin, as_root, api_db, file_form):

    # Dupe of test_queue.py
    gear_doc = default_payload['gear']['gear']
    gear_doc['inputs'] = {
        'dicom': {
            'base': 'file'
        }
    }
    gear = data_builder.create_gear(gear=gear_doc)
    invalid_gear = data_builder.create_gear(gear={'custom': {'flywheel': {'invalid': True}}})
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()
    assert as_admin.post('/acquisitions/' + acquisition + '/files', files=file_form('test.zip')).ok

    job_data = {
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

    # try to add job w/ non-existent gear
    job0 = copy.deepcopy(job_data)
    job0['gear_id'] = '000000000000000000000000'
    r = as_admin.post('/jobs/add', json=job0)
    assert r.status_code == 400

    # add job with explicit destination
    r = as_admin.post('/jobs/add', json=job_data)
    assert r.ok
    job1_id = r.json()['_id']

    # get job
    r = as_root.get('/jobs/' + job1_id)
    assert r.ok

    # get job log (empty)
    r = as_admin.get('/jobs/' + job1_id + '/logs')
    assert r.ok
    assert r.json()['logs'] == []

    # try to add job log w/o root
    # needed to use as_user because root = true for as_admin
    job_logs = [{'fd': 1, 'msg': 'Hello'}, {'fd': 2, 'msg': 'World'}]
    r = as_user.post('/jobs/' + job1_id + '/logs', json=job_logs)
    assert r.status_code == 403

    # try to add job log to non-existent job
    r = as_root.post('/jobs/000000000000000000000000/logs', json=job_logs)
    assert r.status_code == 404

    # get job log as text w/o logs
    r = as_admin.get('/jobs/' + job1_id + '/logs/text')
    assert r.ok
    assert r.text == '<span class="fd--1">No logs were found for this job.</span>'

    # get job log as html w/o logs
    r = as_admin.get('/jobs/' + job1_id + '/logs/html')
    assert r.ok
    assert r.text == '<span class="fd--1">No logs were found for this job.</span>'

    # add job log
    r = as_root.post('/jobs/' + job1_id + '/logs', json=job_logs)
    assert r.ok

    # try to get job log of non-existent job
    r = as_admin.get('/jobs/000000000000000000000000/logs')
    assert r.status_code == 404

    # get job log (non-empty)
    r = as_admin.get('/jobs/' + job1_id + '/logs')
    assert r.ok
    assert len(r.json()['logs']) == 2

    # add same logs again (for testing text/html logs)
    r = as_root.post('/jobs/' + job1_id + '/logs', json=job_logs)
    assert r.ok

    # get job log as text
    r = as_admin.get('/jobs/' + job1_id + '/logs/text')
    assert r.ok
    assert r.text == 2 * ''.join(log['msg'] for log in job_logs)

    # get job log as html
    r = as_admin.get('/jobs/' + job1_id + '/logs/html')
    assert r.ok
    assert r.text == 2 * ''.join('<span class="fd-{fd}">{msg}</span>\n'.format(**log) for log in job_logs)

    # get job config
    r = as_root.get('/jobs/' + job1_id + '/config.json')
    assert r.ok

    # try to cancel job w/o permission (different user)
    r = as_user.put('/jobs/' + job1_id, json={'state': 'cancelled'})
    assert r.status_code == 403

    # try to update job (user may only cancel)
    api_db.jobs.update_one({'_id': bson.ObjectId(job1_id)}, {'$set': {'origin.id': 'user@user.com'}})
    r = as_user.put('/jobs/' + job1_id, json={'test': 'invalid'})
    assert r.status_code == 403

    # add job with implicit destination
    job2 = copy.deepcopy(job_data)
    del job2['destination']
    r = as_admin.post('/jobs/add', json=job2)
    assert r.ok

    # add job with invalid gear
    job3 = copy.deepcopy(job_data)
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

    # set next job to failed
    r = as_root.put('/jobs/' + next_job_id, json={'state': 'failed'})
    assert r.ok

    # retry failed job
    r = as_root.post('/jobs/' + next_job_id + '/retry')
    assert r.ok

    # get next job as admin
    r = as_admin.get('/jobs/next', params={'tags': 'test-tag'})
    assert r.ok
    next_job_id = r.json()['id']

    # set next job to failed
    r = as_root.put('/jobs/' + next_job_id, json={'state': 'failed'})
    assert r.ok

    # retry failed job w/o root
    r = as_admin.post('/jobs/' + next_job_id + '/retry')
    assert r.ok

    # set as_user perms to ro
    r = as_user.get('/users/self')
    assert r.ok
    uid = r.json()['_id']

    r = as_admin.post('/projects/' + project + '/permissions', json={
        '_id': uid,
        'access': 'ro',
        'phi-access': True
    })
    assert r.ok

    # try to add job without rw
    r = as_user.post('/jobs/add', json=job_data)
    assert r.status_code == 403

    # set as_user perms to rw
    r = as_admin.put('/projects/' + project + '/permissions/' + uid, json={
        'access': 'rw'
    })
    assert r.ok

    # add job with rw
    r = as_user.post('/jobs/add', json=job_data)
    assert r.ok
    job_rw_id = r.json()['_id']

    # get next job as admin
    r = as_admin.get('/jobs/next', params={'tags': 'test-tag'})
    assert r.ok
    job_rw_id = r.json()['id']

    # Add job with gear that uses api-key base type and get config
    gear_doc = default_payload['gear']['gear']
    gear_doc['inputs'] = {
        'dicom': {
            'base': 'file'
        },
        'api_key': {
            'base': 'api-key'
        }
    }
    gear1 = data_builder.create_gear(gear=gear_doc)

    job4 = copy.deepcopy(job_data)
    job4['gear_id'] = gear1

    r = as_admin.post('/jobs/add', json=job4)
    assert r.status_code == 200
    job_id = r.json()['_id']

    # start job
    r = as_root.put('/jobs/' + job_id, json={'state': 'running'})
    assert r.ok

    # get config
    r = as_root.get('/jobs/'+ job_id +'/config.json')
    assert r.ok
    config = r.json()

    assert type(config['inputs']['dicom']) is dict
    assert config['destination']['id'] == acquisition
    assert type(config['config']) is dict
    api_key = config['inputs']['api_key']['key']

    # ensure api_key works
    as_job_key = as_public
    as_job_key.headers.update({'Authorization': 'scitran-user ' + api_key})
    r = as_job_key.get('/users/self')
    assert r.ok

    # complete job and ensure API key no longer works
    r = as_root.put('/jobs/' + job_id, json={'state': 'complete'})
    assert r.ok

    r = as_job_key.get('/users/self')
    assert r.status_code == 401

    # try to add job with no inputs and no destination
    gear_doc = default_payload['gear']['gear']
    gear_doc['inputs'] = {}
    gear2 = data_builder.create_gear(gear=gear_doc)

    job5 = copy.deepcopy(job_data)
    job5['gear_id'] = gear2
    job5.pop('inputs')
    job5.pop('destination')

    r = as_admin.post('/jobs/add', json=job5)
    assert r.status_code == 400

    # try to add job with input type that is not file nor api-key
    gear_doc = default_payload['gear']['gear']
    gear_doc['inputs'] = {
        'dicom': {
            'base': 'made-up'
        }
    }
    gear3 = str(api_db.gears.insert(gear_doc))

    job6 = copy.deepcopy(job_data)
    job6['gear_id'] = gear3

    r = as_admin.post('/jobs/add', json=job6)
    assert r.status_code == 500

    # Attempt to set a malformed file reference as input
    job7 = copy.deepcopy(job_data)
    job7['inputs'] = {
        'dicom': {
                # missing type
                'id': acquisition,
                'name': 'test.zip'
        }
    }
    r = as_admin.post('/jobs/add', json=job7)
    assert r.status_code == 400

    # Insert non-running job into database
    job_instance = {
        "_id" : bson.ObjectId("5a007cdb0f352600d94c845f"),
        "inputs" : [{
            "input": 'dicom',
            'type': 'acquisition',
            'id': acquisition,
            'name': 'test.zip'
        }],
        # Set attempt to 5 so that job isn't retried, throwing off the usage report tests
        "attempt" : 5,
        "tags" : [
            "ad-hoc"
        ],
        "destination" : {
            "type" : "acquisition",
            "id" : acquisition
        },
        "modified" : datetime.datetime(1980, 1, 1),
        "created" : datetime.datetime(1980, 1, 1),
        "produced_metadata" : {},
        "saved_files" : [],
        "state" : "running",
        "gear_id" : gear3,
        "batch" : None,
    }
    api_db.jobs.insert_one(job_instance)
    r = as_root.post('/jobs/reap')
    assert r.ok
    assert r.json().get('orphaned') == 1
    r = as_admin.get('/jobs/'+str(job_instance['_id'])+'/logs')
    assert r.ok
    assert "The job did not report in for a long time and was canceled." in [log["msg"] for log in r.json()['logs']]
    api_db.jobs.delete_one({"_id": bson.ObjectId("5a007cdb0f352600d94c845f")})


def test_analysis_job_creation_errors(data_builder, default_payload, as_admin, file_form):
    project = data_builder.create_project()
    session = data_builder.create_session()
    gear_doc = default_payload['gear']['gear']
    gear_doc['inputs'] = {
        'csv': {
            'base': 'file'
        }
    }
    gear = data_builder.create_gear(gear=gear_doc)

    # Add project file
    r = as_admin.post('/projects/' + project + '/files', files=file_form('job_1.csv'))
    assert r.ok

    # ensure analysis with improper gear id is not created
    r = as_admin.post('/sessions/' + session + '/analyses', params={'job': 'true'}, json={
        'analysis': {'label': 'with-job'},
        'job': {
            # no gear id
            'inputs': {
                'csv': {'type': 'project', 'id': project, 'name': 'job_1.csv'}
            }
        }
    })
    assert r.status_code == 400
    assert len(as_admin.get('/sessions/' + session).json().get('analyses', [])) == 0

    # ensure analysis with improper inputs is not created
    r = as_admin.post('/sessions/' + session + '/analyses', params={'job': 'true'}, json={
        'analysis': {'label': 'with-job'},
        'job': {
            'gear_id': gear,
            'inputs': {
                'made-up': {'type': 'project', 'id': project, 'name': 'job_1.csv'}
            }
        }
    })
    assert r.status_code == 400
    assert len(as_admin.get('/sessions/' + session).json().get('analyses', [])) == 0
