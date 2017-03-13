import datetime
import dateutil.parser
import os
import json
import time
import pytest
import logging

from api.web.request import AccessType

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)



@pytest.fixture()
def with_hierarchy_and_file_data(api_as_admin, bunch, request, data_builder):
    group =         data_builder.create_group('test_upload_' + str(int(time.time() * 1000)))
    project =       data_builder.create_project(group)
    session =       data_builder.create_session(project)
    acquisition =   data_builder.create_acquisition(session)

    file_names = ['one.csv', 'two.csv', 'three.csv', 'four.csv']
    for name in file_names:
        file_data = {'file1': (name, 'some,data,to,send\nanother,row,to,send\n')}
        r = api_as_admin.post('/acquisitions/' + acquisition + '/files', files=file_data)
        assert r.ok

    def teardown_db():
        data_builder.delete_acquisition(acquisition)
        data_builder.delete_session(session)
        data_builder.delete_project(project)
        data_builder.delete_group(group)

    request.addfinalizer(teardown_db)

    fixture_data = bunch.create()
    fixture_data.group = group
    fixture_data.project = project
    fixture_data.session = session
    fixture_data.acquisition = acquisition
    return fixture_data


def test_archive_file(with_hierarchy_and_file_data, api_as_user):
    data = with_hierarchy_and_file_data

    r = api_as_user.get('/acquisitions/' + data.acquisition)
    assert r.ok
    files = json.loads(r.content)['files']
    file_name = files[0]['name']
    # Assert the files are all there
    assert len(files) ==  4

    log.warn('file_name is {}'.format(file_name))


    # Archive the first file
    file_update = json.dumps({'archived': True})
    r = api_as_user.put('/acquisitions/' + data.acquisition + '/files/' + file_name, data=file_update)
    assert r.ok

    r = api_as_user.get('/acquisitions/' + data.acquisition)
    assert r.ok
    files = json.loads(r.content)['files']

    # Assert only the non-archived files are returned
    assert len(files) ==  3


    # Ensure sessions list endpoint doesn't return archived files
    r = api_as_user.get('/sessions/' + data.session + '/acquisitions')
    assert r.ok
    acquisitions = json.loads(r.content)
    assert len(acquisitions) == 1
    files = acquisitions[0]['files']

    # Assert only the non-archived files are returned
    assert len(files) ==  3


    # Use query param to return all files
    r = api_as_user.get('/acquisitions/' + data.acquisition, params={'archived': True})
    assert r.ok
    files = json.loads(r.content)['files']

    # Assert all the files are returned
    assert len(files) ==  4


    # Use query param to return all files for sessions list endpoint
    r = api_as_user.get('/sessions/' + data.session + '/acquisitions', params={'archived': True})
    assert r.ok
    acquisitions = json.loads(r.content)
    assert len(acquisitions) == 1
    files = acquisitions[0]['files']

    # Assert all the files are returned
    assert len(files) ==  4


    # Unarchive the file
    file_update = json.dumps({'archived': False})
    r = api_as_user.put('/acquisitions/' + data.acquisition + '/files/' + file_name, data=file_update)
    assert r.ok

    r = api_as_user.get('/acquisitions/' + data.acquisition)
    assert r.ok
    files = json.loads(r.content)['files']

    # Assert all the files are returned again
    assert len(files) ==  4

