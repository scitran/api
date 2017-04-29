import copy
import datetime
import json

import dateutil.parser
import pytest


# TODO switch to upload_file_form in all uid(-match)/label/reaper upload tests
# after #772 (coverage-low-hanging 3) gets merged to avoid conflict hell
@pytest.fixture(scope='function')
def upload_file_form(file_form, merge_dict, randstr):
    def create_form(**meta_override):
        prefix = randstr()
        names = ('project', 'subject', 'session', 'acquisition', 'unused')
        files = {name: '{}-{}.csv'.format(prefix, name) for name in names}
        meta = {
            'project': {
                'label': prefix + '-project-label',
                'files': [{'name': files['project']}]
            },
            'session': {
                'uid': prefix + '-session-uid',
                'label': prefix + '-session-label',
                'subject': {
                    'code': prefix + '-subject-code',
                    'files': [{'name': files['subject']}]
                },
                'files': [{'name': files['session']}]
            },
            'acquisition': {
                'uid': prefix + '-acquisition-uid',
                'label': prefix + '-acquisition-label',
                'files': [{'name': files['acquisition']}]
            }
        }
        if meta_override:
            merge_dict(meta, meta_override)
        return file_form(*files.values(), meta=meta)

    return create_form


def test_reaper_upload(data_builder, randstr, upload_file_form, as_admin):
    group_1 = data_builder.create_group()
    prefix = randstr()
    project_label_1 = prefix + '-project-label-1'
    session_uid = prefix + '-session-uid'

    # reaper-upload files to group_1/project_label_1 using session_uid
    r = as_admin.post('/upload/reaper', files=upload_file_form(
        group={'_id': group_1},
        project={'label': project_label_1},
        session={'uid': session_uid},
    ))
    assert r.ok

    # get session created by the upload
    project_1 = as_admin.get('/groups/' + group_1 + '/projects').json()[0]['_id']
    session = as_admin.get('/projects/' + project_1 + '/sessions').json()[0]['_id']
    assert len(as_admin.get('/projects/' + project_1 + '/sessions').json()) == 1
    assert len(as_admin.get('/sessions/' + session + '/acquisitions').json()) == 1
    assert len(as_admin.get('/sessions/' + session).json()['files']) == 1

    # move session to group_2/project_2
    group_2 = data_builder.create_group()
    project_2 = data_builder.create_project(group=group_2, label=prefix + '-project-label-2')
    as_admin.put('/sessions/' + session, json={'project': project_2})
    assert len(as_admin.get('/projects/' + project_1 + '/sessions').json()) == 0
    assert len(as_admin.get('/projects/' + project_2 + '/sessions').json()) == 1

    # reaper-upload files using existing session_uid and incorrect group/project
    r = as_admin.post('/upload/reaper', files=upload_file_form(
        group={'_id': group_1},
        project={'label': project_label_1},
        session={'uid': session_uid},
    ))
    assert r.ok

    # verify no new sessions were created and that group/project was ignored
    # NOTE uploaded project file is NOT stored in this scenario!
    assert len(as_admin.get('/projects/' + project_1 + '/sessions').json()) == 0
    assert len(as_admin.get('/projects/' + project_2 + '/sessions').json()) == 1

    # verify that acquisition creation/file uploads worked
    assert len(as_admin.get('/sessions/' + session + '/acquisitions').json()) == 2
    assert len(as_admin.get('/sessions/' + session).json()['files']) == 2

    # clean up
    data_builder.delete_group(group_1, recursive=True)
    data_builder.delete_group(group_2, recursive=True)


def test_uid_upload(data_builder, file_form, as_admin, as_user, as_public):
    group = data_builder.create_group()

    # try to uid-upload w/o logging in
    r = as_public.post('/upload/uid')
    assert r.status_code == 403

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

    # try to uid-upload to new project w/o group rw perms
    r = as_user.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.status_code == 403

    # uid-upload files
    r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.ok

    # try to uid-upload to existing project w/o project rw perms
    uid_meta_2 = copy.deepcopy(uid_meta)
    uid_meta_2['session']['uid'] = uid_meta_2['acquisition']['uid'] = 'uid_upload_2'
    r = as_user.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta_2))
    assert r.status_code == 403

    # uid-upload to existing project but new session uid
    r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta_2))
    assert r.ok

    # uid-upload files to existing session uid
    r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.ok

    # try uid-upload files to existing session uid w/ other user (having no rw perms on session)
    r = as_user.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta))
    assert r.status_code == 403

    # TODO figure out why api.dao.hierarchy._group_id_fuzzy_match is NOT called below

    # # uid-upload to fat-fingered group id (should end up in group)
    # uid_meta_fuzzy = copy.deepcopy(uid_meta)
    # uid_meta_fuzzy['group']['_id'] = 'c' + group
    # r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta_fuzzy))
    # assert r.ok

    # # uid-upload to utterly non-existent group id (should end up in unknown group)
    # uid_meta_unknown = copy.deepcopy(uid_meta)
    # uid_meta_unknown['group']['_id'] = '0000000000000000000000000'
    # r = as_admin.post('/upload/uid', files=file_form(*uid_files, meta=uid_meta_unknown))
    # assert r.ok

    # uid-match-upload files (to the same session and acquisition uid's as above)
    uid_match_meta = copy.deepcopy(uid_meta)
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


def test_multi_upload(data_builder, upload_file_form, randstr, as_admin):
    # test uid-uploads respecting existing uids
    fixed_uid = randstr()
    fixed_uid_group = data_builder.create_group(_id=fixed_uid)
    fixed_uid_form_args = dict(
        group={'_id': fixed_uid_group},
        project={'label': fixed_uid + '-project-label'},
        session={'uid': fixed_uid + '-fixed-uid'},
        acquisition={'uid': fixed_uid + '-fixed-uid'},
    )

    # uid-upload #1 w/ fixed uid
    r = as_admin.post('/upload/uid', files=upload_file_form(**fixed_uid_form_args))
    assert r.ok

    # get newly created project/session/acquisition
    project = as_admin.get('/groups/' + fixed_uid_group + '/projects').json()[0]['_id']
    session = as_admin.get('/projects/' + project + '/sessions').json()[0]['_id']
    acquisition = as_admin.get('/sessions/' + session + '/acquisitions').json()[0]['_id']

    # test uploaded files
    assert len(as_admin.get('/projects/' + project).json()['files']) == 1
    assert len(as_admin.get('/sessions/' + session).json()['files']) == 1
    assert len(as_admin.get('/acquisitions/' + acquisition).json()['files']) == 1

    # uid-upload #2 w/ fixed uid
    r = as_admin.post('/upload/uid', files=upload_file_form(**fixed_uid_form_args))
    assert r.ok

    # test hierarchy (should have no new containers)
    assert len(as_admin.get('/groups/' + fixed_uid_group + '/projects').json()) == 1
    assert len(as_admin.get('/projects/' + project + '/sessions').json()) == 1
    assert len(as_admin.get('/sessions/' + session + '/acquisitions').json()) == 1

    # test uploaded files
    assert len(as_admin.get('/projects/' + project).json()['files']) == 2
    assert len(as_admin.get('/sessions/' + session).json()['files']) == 2
    assert len(as_admin.get('/acquisitions/' + acquisition).json()['files']) == 2

    # label-upload w/ fixed uid
    r = as_admin.post('/upload/label', files=upload_file_form(**fixed_uid_form_args))
    assert r.ok

    # test hierarchy (should have new session)
    assert len(as_admin.get('/groups/' + fixed_uid_group + '/projects').json()) == 1
    assert len(as_admin.get('/projects/' + project + '/sessions').json()) == 2

    # test label-uploads respecting existing labels
    # NOTE subject.code is also checked when label-matching sessions!
    fixed_label = randstr()
    fixed_label_group = data_builder.create_group(_id=fixed_label)
    fixed_label_form_args = dict(
        group={'_id': fixed_label_group},
        project={'label': fixed_label + '-project-label'},
        session={'label': fixed_label + '-fixed-label', 'subject': {'code': fixed_label + '-subject-code'}},
        acquisition={'label': fixed_label + '-fixed-label'},
    )

    # label-upload #1 w/ fixed label
    r = as_admin.post('/upload/label', files=upload_file_form(**fixed_label_form_args))
    assert r.ok

    # get newly created project/session/acquisition
    project = as_admin.get('/groups/' + fixed_label_group + '/projects').json()[0]['_id']
    session = as_admin.get('/projects/' + project + '/sessions').json()[0]['_id']
    acquisition = as_admin.get('/sessions/' + session + '/acquisitions').json()[0]['_id']

    # test uploaded files
    assert len(as_admin.get('/projects/' + project).json()['files']) == 1
    assert len(as_admin.get('/sessions/' + session).json()['files']) == 1
    assert len(as_admin.get('/acquisitions/' + acquisition).json()['files']) == 1

    # label-upload #2 w/ fixed label
    r = as_admin.post('/upload/label', files=upload_file_form(**fixed_label_form_args))
    assert r.ok

    # test hierarchy (should have no new containers)
    assert len(as_admin.get('/groups/' + fixed_label_group + '/projects').json()) == 1
    assert len(as_admin.get('/projects/' + project + '/sessions').json()) == 1
    assert len(as_admin.get('/sessions/' + session + '/acquisitions').json()) == 1

    # test uploaded files
    assert len(as_admin.get('/projects/' + project).json()['files']) == 2
    assert len(as_admin.get('/sessions/' + session).json()['files']) == 2
    assert len(as_admin.get('/acquisitions/' + acquisition).json()['files']) == 2

    # uid-upload w/ fixed label
    r = as_admin.post('/upload/uid', files=upload_file_form(**fixed_label_form_args))
    assert r.ok

    # test hierarchy (should have new session)
    assert len(as_admin.get('/groups/' + fixed_label_group + '/projects').json()) == 1
    assert len(as_admin.get('/projects/' + project + '/sessions').json()) == 2

    # clean up
    data_builder.delete_group(fixed_uid_group, recursive=True)
    data_builder.delete_group(fixed_label_group, recursive=True)


def find_file_in_array(filename, files):
    for f in files:
        if f.get('name') == filename:
            return f


def test_engine_upload_errors(as_drone, as_user):
    # try engine upload w/ non-root
    r = as_user.post('/engine')
    assert r.status_code == 402

    # try engine upload w/o level
    r = as_drone.post('/engine', params={})
    assert r.status_code == 400

    # try engine upload w/ invalid level
    r = as_drone.post('/engine', params={'level': 'what'})
    assert r.status_code == 400

    # try engine upload w/o id
    r = as_drone.post('/engine', params={'level': 'project'})
    assert r.status_code == 400


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


def test_packfile_upload(data_builder, file_form, as_admin, as_root, api_db):
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

    # get another token (start packfile-upload)
    r = as_admin.post('/projects/' + project + '/packfile-start')
    assert r.ok
    token = r.json()['token']

    # upload to packfile
    r = as_admin.post('/projects/' + project + '/packfile',
        params={'token': token}, files=file_form('two.csv'))
    assert r.ok

    # expire upload token
    expired_time = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
    api_db.tokens.update({'_id': token}, {'$set': {'modified': expired_time}})

    # try to clean packfile tokens w/o root
    r = as_admin.post('/clean-packfiles')
    assert r.status_code == 402

    r = as_root.post('/clean-packfiles')
    assert r.ok
    assert r.json()['removed']['tokens'] > 0

    # clean up added session/acquisition
    data_builder.delete_project(project, recursive=True)
