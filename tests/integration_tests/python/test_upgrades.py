import os
import sys

import bson
import copy
import pytest


@pytest.fixture(scope='function')
def database(mocker):
    bin_path = os.path.join(os.getcwd(), 'bin')
    mocker.patch('sys.path', [bin_path] + sys.path)
    import database
    return database


def test_42(data_builder, api_db, as_admin, database):
    # Mimic old-style archived flag
    session = data_builder.create_session()
    session2 = data_builder.create_session()
    api_db.sessions.update_one({'_id': bson.ObjectId(session)}, {'$set': {'archived': True}})
    api_db.sessions.update_one({'_id': bson.ObjectId(session2)}, {'$set': {'archived': False}})

    # Verfiy archived session is not hidden anymore
    assert session  in [s['_id'] for s in as_admin.get('/sessions').json()]

    # Verify upgrade creates new-style hidden tag
    database.upgrade_to_42()
    session_data = as_admin.get('/sessions/' + session).json()
    assert 'archived' not in session_data
    assert 'hidden' in session_data['tags']

    # Verify archived was removed when false as well
    session_data = as_admin.get('/sessions/' + session2).json()
    assert 'archived' not in session_data


def test_43(data_builder, randstr, api_db, as_admin, database, file_form):

    # Set up files with measurements

    assert True

    containers = [
        ('collections',  data_builder.create_collection()),
        ('projects',     data_builder.create_project()),
        ('sessions',     data_builder.create_session()),
        ('acquisitions', data_builder.create_acquisition())
    ]

    for c in containers:
        assert as_admin.post('/{}/{}/files'.format(c[0], c[1]), files=file_form('test.csv')).ok
        assert as_admin.post('/{}/{}/files'.format(c[0], c[1]), files=file_form('test2.csv')).ok
        api_db[c[0]].update_one({'_id': bson.ObjectId(c[1])},
            {'$set': { # Mangoes ...
                'files.0.measurements': ['diffusion', 'functional'],
                'files.1.measurements': ['diffusion', 'functional']
            }})


    # Set up rules referencing measurements

    rule = {
        'all' : [
            {'type' : 'file.measurement', 'value' : 'diffusion'},
            {'type' : 'container.has-measurement', 'value' : 'tests', 'regex': True}
        ],
        'any' : [
            {'type' : 'file.measurement', 'value' : 'diffusion'},
            {'type' : 'container.has-measurement', 'value' : 'tests', 'regex': True}
        ],
        'name' : 'Run dcm2niix on dicom',
        'alg' : 'dcm2niix',
        'project_id' : 'site'
    }

    api_db.project_rules.insert(copy.deepcopy(rule))
    api_db.project_rules.insert(copy.deepcopy(rule))


    # Set up session templates referencing measurements

    t_project1 = data_builder.create_project()
    t_project2 = data_builder.create_project()

    template = {
        'session': {'subject': {'code': '^compliant$'}},
        'acquisitions': [{
            'minimum': 1,
            'files': [{
                'minimum': 2,
                'measurements': 'diffusion'
            }]
        }]
    }

    assert as_admin.post('/projects/' + t_project1 + '/template', json=template).ok
    assert as_admin.post('/projects/' + t_project2 + '/template', json=template).ok


    ### RUN UPGRADE

    database.upgrade_to_43()

    ####


    # Ensure files were updated
    for c in containers:
        files = as_admin.get('/{}/{}'.format(c[0], c[1])).json()['files']
        for f in files:
            assert f['classification'] == {'Custom': ['diffusion', 'functional']}


    # Ensure rules were updated
    rule_after = {
        'all' : [
            {'type' : 'file.classification', 'value' : 'diffusion'},
            {'type' : 'container.has-classification', 'value' : 'tests', 'regex': True}
        ],
        'any' : [
            {'type' : 'file.classification', 'value' : 'diffusion'},
            {'type' : 'container.has-classification', 'value' : 'tests', 'regex': True}
        ],
        'name' : 'Run dcm2niix on dicom',
        'alg' : 'dcm2niix'
    }

    rules = as_admin.get('/site/rules').json()
    for r in rules:
        r.pop('_id')
        assert r == rule_after


    # Ensure templates were updated
    template_after = {
        'session': {'subject': {'code': '^compliant$'}},
        'acquisitions': [{
            'minimum': 1,
            'files': [{
                'minimum': 2,
                'classification': 'diffusion'
            }]
        }]
    }
    for p in [t_project1, t_project2]:
        assert as_admin.get('/projects/' + p).json()['template'] == template_after



