import json

import dateutil.parser


def test_upload_without_login(as_public):
    r = as_public.post('/upload/uid')
    assert r.status_code == 403


def test_uid_upload(data_builder, file_form, as_admin, as_user):
    group = data_builder.create_group()

    # try to uid-upload w/o metadata
    r = as_admin.post('/upload/uid', files=file_form('test.csv'))
    assert r.status_code == 500

    # NOTE unused.csv is testing code that discards files not referenced from meta
    uid_files = ('project.csv', 'subject.csv', 'session.csv', 'acquisition.csv', 'unused.csv')
    uid_meta = {
        'group': {'_id': group},
        'project': {
            'label': 'uid_upload',
            'files': [{'name': 'project.csv'}]
        },
        'session': {
            'uid': 'uid_upload',
            'subject': {
                'code': 'uid_upload',
                'files': [{'name': 'subject.csv'}]
            },
            'files': [{'name': 'session.csv'}]
        },
        'acquisition': {
            'uid': 'uid_upload',
            'files': [{'name': 'acquisition.csv'}]
        }
    }

    # uid-upload files
    r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.ok

    # uid-upload files to existing session uid
    r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.ok

    # try uid-upload files to existing session uid w/ other user (having no rw perms on session)
    r = as_user.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.status_code == 403

    # uid-match-upload files (to the same session and acquisition uid's as above)
    uid_match_meta = uid_meta.copy()
    del uid_match_meta['group']
    r = as_admin.post('/upload/uid-match', files=file_form(*uid_files, meta=uid_match_meta))
    assert r.ok

    # try uid-match upload w/ other user (having no rw permissions on session)
    r = as_user.post('/upload/uid-match', files=file_form(*uid_files, meta=uid_match_meta))
    assert r.status_code == 403

    # try uid-match upload w/ non-existent acquisition uid
    uid_match_meta['acquisition']['uid'] = 'nonexistent_uid'
    r = as_admin.post('/upload/uid-match', files=file_form(*uid_files, meta=uid_match_meta))
    assert r.status_code == 404

    # try uid-match upload w/ non-existent session uid
    uid_match_meta['session']['uid'] = 'nonexistent_uid'
    r = as_admin.post('/upload/uid-match', files=file_form(*uid_files, meta=uid_match_meta))
    assert r.status_code == 404

    # delete group and children recursively (created by upload)
    data_builder.delete_group(group, recursive=True)


def test_label_upload(data_builder, file_form, as_admin):
    group = data_builder.create_group()

    # label-upload files
    r = as_admin.post('/upload/label', files=file_form(
        'project.csv', 'subject.csv', 'session.csv', 'acquisition.csv', 'unused.csv',
        meta={
            'group': {'_id': group},
            'project': {
                'label': 'test_project',
                'files': [{'name': 'project.csv'}]
            },
            'session': {
                'label': 'test_session_label',
                'subject': {
                    'code': 'test_subject_code',
                    'files': [{'name': 'subject.csv'}]
                },
                'files': [{'name': 'session.csv'}]
            },
            'acquisition': {
                'label': 'test_acquisition_label',
                'files': [{'name': 'acquisition.csv'}]
            }
        })
    )
    assert r.ok

    # delete group and children recursively (created by upload)
    data_builder.delete_group(group, recursive=True)


def find_file_in_array(filename, files):
    for f in files:
        if f.get('name') == filename:
            return f

def test_acquisition_engine_upload(data_builder, file_form, as_root):
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()
    job = data_builder.create_job(inputs={
        'test': {'type': 'acquisition', 'id': acquisition, 'name': 'test'}
    })

    metadata = {
        'project':{
            'label': 'engine project',
            'info': {'test': 'p'}
        },
        'session':{
            'label': 'engine session',
            'subject': {'code': 'engine subject'},
            'info': {'test': 's'}
        },
        'acquisition':{
            'label': 'engine acquisition',
            'timestamp': '2016-06-20T21:57:36+00:00',
            'info': {'test': 'a'},
            'files':[
                {
                    'name': 'one.csv',
                    'type': 'engine type 0',
                    'info': {'test': 'f0'}
                },
                {
                    'name': 'two.csv',
                    'type': 'engine type 1',
                    'info': {'test': 'f1'}
                }
            ]
        }
    }
    # try engine upload w/ non-existent job_id
    r = as_root.post('/engine',
        params={'level': 'acquisition', 'id': acquisition, 'job': '000000000000000000000000'},
        files=file_form('one.csv', 'two.csv', meta=metadata)
    )
    assert r.status_code == 500

    # engine upload
    r = as_root.post('/engine',
        params={'level': 'acquisition', 'id': acquisition, 'job': job},
        files=file_form('one.csv', 'two.csv', meta=metadata)
    )
    assert r.ok

    r = as_root.get('/projects/' + project)
    assert r.ok
    p = r.json()
    # Engine metadata should not replace existing fields
    assert p['label'] != metadata['project']['label']
    assert p['info'] == metadata['project']['info']

    r = as_root.get('/sessions/' + session)
    assert r.ok
    s = r.json()
    # Engine metadata should not replace existing fields
    assert s['label'] != metadata['session']['label']
    assert s['info'] == metadata['session']['info']
    assert s['subject']['code'] == metadata['session']['subject']['code']

    r = as_root.get('/acquisitions/' + acquisition)
    assert r.ok
    a = r.json()
    # Engine metadata should not replace existing fields
    assert a['label'] != metadata['acquisition']['label']
    assert a['info'] == metadata['acquisition']['info']
    a_timestamp = dateutil.parser.parse(a['timestamp'])
    m_timestamp = dateutil.parser.parse(metadata['acquisition']['timestamp'])
    assert a_timestamp == m_timestamp

    for f in a['files']:
        mf = find_file_in_array(f['name'], metadata['acquisition']['files'])
        assert mf is not None
        assert f['type'] == mf['type']
        assert f['info'] == mf['info']


def test_session_engine_upload(data_builder, file_form, as_root):
    project = data_builder.create_project()
    session = data_builder.create_session()

    metadata = {
        'project':{
            'label': 'engine project',
            'info': {'test': 'p'}
        },
        'session':{
            'label': 'engine session',
            'subject': {'code': 'engine subject'},
            'timestamp': '2016-06-20T21:57:36+00:00',
            'info': {'test': 's'},
            'files': [
                {
                    'name': 'one.csv',
                    'type': 'engine type 0',
                    'info': {'test': 'f0'}
                },
                {
                    'name': 'two.csv',
                    'type': 'engine type 1',
                    'info': {'test': 'f1'}
                }
            ]
        }
    }

    r = as_root.post('/engine',
        params={'level': 'session', 'id': session},
        files=file_form('one.csv', 'two.csv', meta=metadata)
    )
    assert r.ok

    r = as_root.get('/projects/' + project)
    assert r.ok
    p = r.json()
    # Engine metadata should not replace existing fields
    assert p['label'] != metadata['project']['label']
    assert p['info'] == metadata['project']['info']

    r = as_root.get('/sessions/' + session)
    assert r.ok
    s = r.json()
    # Engine metadata should not replace existing fields
    assert s['label'] != metadata['session']['label']
    assert s['info'] == metadata['session']['info']
    assert s['subject']['code'] == metadata['session']['subject']['code']
    s_timestamp = dateutil.parser.parse(s['timestamp'])
    m_timestamp = dateutil.parser.parse(metadata['session']['timestamp'])
    assert s_timestamp == m_timestamp

    for f in s['files']:
        mf = find_file_in_array(f['name'], metadata['session']['files'])
        assert mf is not None
        assert f['type'] == mf['type']
        assert f['info'] == mf['info']

def test_project_engine_upload(data_builder, file_form, as_root):
    project = data_builder.create_project()
    metadata = {
        'project':{
            'label': 'engine project',
            'info': {'test': 'p'},
            'files': [
                {
                    'name': 'one.csv',
                    'type': 'engine type 0',
                    'info': {'test': 'f0'}
                },
                {
                    'name': 'two.csv',
                    'type': 'engine type 1',
                    'info': {'test': 'f1'}
                }
            ]
        }
    }

    r = as_root.post('/engine',
        params={'level': 'project', 'id': project},
        files=file_form('one.csv', 'two.csv', meta=metadata)
    )
    assert r.ok

    r = as_root.get('/projects/' + project)
    assert r.ok
    p = r.json()
    # Engine metadata should not replace existing fields
    assert p['label'] != metadata['project']['label']
    assert p['info'] == metadata['project']['info']

    for f in p['files']:
        mf = find_file_in_array(f['name'], metadata['project']['files'])
        assert mf is not None
        assert f['type'] == mf['type']
        assert f['info'] == mf['info']


def test_acquisition_file_only_engine_upload(data_builder, file_form, as_root):
    acquisition = data_builder.create_acquisition()
    file_names = ['one.csv', 'two.csv']

    r = as_root.post('/engine',
        params={'level': 'acquisition', 'id': acquisition},
        files=file_form(*file_names)
    )
    assert r.ok

    r = as_root.get('/acquisitions/' + acquisition)
    assert r.ok
    assert set(f['name'] for f in r.json()['files']) == set(file_names)


def test_acquisition_subsequent_file_engine_upload(data_builder, file_form, as_root):
    acquisition = data_builder.create_acquisition()

    file_name_1 = 'one.csv'
    r = as_root.post('/engine',
        params={'level': 'acquisition', 'id': acquisition},
        files=file_form(file_name_1, meta={
            'acquisition': {
                'files': [{
                    'name': file_name_1,
                    'type': 'engine type 1',
                    'info': {'test': 'f1'}
                }]
            }
        })
    )
    assert r.ok

    r = as_root.get('/acquisitions/' + acquisition)
    assert r.ok
    assert set(f['name'] for f in r.json()['files']) == set([file_name_1])

    file_name_2 = 'two.csv'
    r = as_root.post('/engine',
        params={'level': 'acquisition', 'id': acquisition},
        files=file_form(file_name_2, meta={
            'acquisition': {
                'files': [{
                    'name': file_name_2,
                    'type': 'engine type 2',
                    'info': {'test': 'f2'}
                }]
            }
        })
    )
    assert r.ok

    r = as_root.get('/acquisitions/' + acquisition)
    assert r.ok
    assert set(f['name'] for f in r.json()['files']) == set([file_name_1, file_name_2])


def test_acquisition_metadata_only_engine_upload(data_builder, file_form, as_root):
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    metadata = {
        'project': {
            'label': 'engine project',
            'info': {'test': 'p'}
        },
        'session':{
            'label': 'engine session',
            'subject': {'code': 'engine subject'},
            'info': {'test': 's'}
        },
        'acquisition':{
            'label': 'engine acquisition',
            'timestamp': '2016-06-20T21:57:36+00:00',
            'info': {'test': 'a'}
        }
    }

    r = as_root.post('/engine',
        params={'level': 'acquisition', 'id': acquisition},
        files=file_form(meta=metadata)
    )
    assert r.ok

    r = as_root.get('/projects/' + project)
    assert r.ok
    p = r.json()
    # Engine metadata should not replace existing fields
    assert p['label'] != metadata['project']['label']
    assert p['info'] == metadata['project']['info']

    r = as_root.get('/sessions/' + session)
    assert r.ok
    s = r.json()
    # Engine metadata should not replace existing fields
    assert s['label'] != metadata['session']['label']
    assert s['info'] == metadata['session']['info']
    assert s['subject']['code'] == metadata['session']['subject']['code']

    r = as_root.get('/acquisitions/' + acquisition)
    assert r.ok
    a = r.json()
    # Engine metadata should not replace existing fields
    assert a['label'] != metadata['acquisition']['label']
    assert a['info'] == metadata['acquisition']['info']
    a_timestamp = dateutil.parser.parse(a['timestamp'])
    m_timestamp = dateutil.parser.parse(metadata['acquisition']['timestamp'])
    assert a_timestamp == m_timestamp


def test_analysis_upload(data_builder, file_form, as_admin):
    gear = data_builder.create_gear()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    # create session analysis
    r = as_admin.post('/sessions/' + session + '/analyses', files=file_form(
        'one.csv', meta={'label': 'test analysis', 'inputs': [{'name': 'one.csv'}]}
    ))
    assert r.ok
    session_analysis = r.json()['_id']

    # delete session analysis
    r = as_admin.delete('/sessions/' + session + '/analyses/' + session_analysis)
    assert r.ok

    # create acquisition analysis
    r = as_admin.post('/acquisitions/' + acquisition + '/analyses', files=file_form(
        'one.csv', meta={'label': 'test analysis', 'inputs': [{'name': 'one.csv'}]}
    ))
    assert r.ok
    acquisition_analysis = r.json()['_id']

    # delete acquisition analysis
    r = as_admin.delete('/acquisitions/' + acquisition + '/analyses/' + acquisition_analysis)
    assert r.ok

    # create acquisition file (for the fixture acquisition)
    r = as_admin.post('/acquisitions/' + acquisition + '/files', files=file_form('one.csv'))
    assert r.ok

    # try to create analysis+job w/ missing analysis/job info
    r = as_admin.post('/sessions/' + session + '/analyses', params={'job': 'true'}, json={})
    assert r.status_code == 400

    # create session analysis (job) using acquisition's file as input
    r = as_admin.post('/sessions/' + session + '/analyses', params={'job': 'true'}, json={
        'analysis': {'label': 'test analysis job'},
        'job': {
            'gear_id': gear,
            'inputs': {
                'csv': {
                    'type': 'acquisition',
                    'id': acquisition,
                    'name': 'one.csv'
                }
            },
            'tags': ['example']
        }
    })
    assert r.ok
    session_analysis = r.json()['_id']

    # delete session analysis (job)
    r = as_admin.delete('/sessions/' + session + '/analyses/' + session_analysis)
    assert r.ok


def test_analysis_engine_upload(data_builder, file_form, as_root):
    acquisition = data_builder.create_acquisition()

    # create acquisition analysis
    r = as_root.post('/acquisitions/' + acquisition + '/analyses', files=file_form(
        'one.csv', meta={'label': 'test analysis', 'inputs': [{'name': 'one.csv'}]}
    ))
    assert r.ok
    acquisition_analysis = r.json()['_id']

    r = as_root.post('/engine',
        params={'level': 'analysis', 'id': acquisition_analysis},
        files=file_form('out.csv', meta={
            'type': 'text',
            'value': {'label': 'test'},
            'enabled': True}
    ))
    assert r.ok

    # delete acquisition analysis
    r = as_root.delete('/acquisitions/' + acquisition + '/analyses/' + acquisition_analysis)
    assert r.ok


def test_packfile(data_builder, file_form, as_admin):
    project = data_builder.create_project()
    session = data_builder.create_session()

    # try to start packfile-upload to non-project target
    r = as_admin.post('/sessions/' + session + '/packfile-start')
    assert r.status_code == 500

    # try to start packfile-upload to non-existent project
    r = as_admin.post('/projects/000000000000000000000000/packfile-start')
    assert r.status_code == 500

    # start packfile-upload
    r = as_admin.post('/projects/' + project + '/packfile-start')
    assert r.ok
    token = r.json()['token']

    # try to upload to packfile w/o token
    r = as_admin.post('/projects/' + project + '/packfile')
    assert r.status_code == 500

    # upload to packfile
    r = as_admin.post('/projects/' + project + '/packfile',
        params={'token': token}, files=file_form('one.csv'))
    assert r.ok

    metadata_json = json.dumps({
        'project': {'_id': project},
        'session': {'label': 'test-packfile-label'},
        'acquisition': {
            'label': 'test-packfile-label',
            'timestamp': '1979-01-01T00:00:00+00:00'
        },
        'packfile': {'type': 'test'}
    })

    # try to finish packfile-upload w/o token
    r = as_admin.post('/projects/' + project + '/packfile-end',
        params={'metadata': metadata_json})
    assert r.status_code == 500

    # try to finish packfile-upload with files in the request
    r = as_admin.post('/projects/' + project + '/packfile-end',
        params={'token': token, 'metadata': metadata_json},
        files={'file': ('packfile-end.txt', 'sending files to packfile-end is not allowed\n')}
    )
    assert r.status_code == 500

    # finish packfile-upload (creates new session/acquisition)
    r = as_admin.post('/projects/' + project + '/packfile-end',
        params={'token': token, 'metadata': metadata_json})
    assert r.ok

    # clean up added session/acquisition
    event_data_start_str = 'event: result\ndata: '
    event_data_start_pos = r.text.find(event_data_start_str)
    event_data = json.loads(r.text[event_data_start_pos + len(event_data_start_str):])
    r = as_admin.delete('/acquisitions/' + event_data['acquisition_id'])
    assert r.ok
    r = as_admin.delete('/sessions/' + event_data['session_id'])
    assert r.ok
