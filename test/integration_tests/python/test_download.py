import cStringIO
import os
import tarfile
import zipfile


def test_download(data_builder, file_form, as_admin, api_db):
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    # upload the same file to each container created and use different tags to
    # facilitate download filter tests:
    # acquisition: [], session: ['plus'], project: ['plus', 'minus']
    file_name = 'test.csv'
    as_admin.post('/acquisitions/' + acquisition + '/files', files=file_form(
        file_name, meta={'name': file_name, 'type': 'csv'}))

    as_admin.post('/sessions/' + session + '/files', files=file_form(
        file_name, meta={'name': file_name, 'type': 'csv', 'tags': ['plus']}))

    as_admin.post('/projects/' + project + '/files', files=file_form(
        file_name, meta={'name': file_name, 'type': 'csv', 'tags': ['plus', 'minus']}))

    missing_object_id = '000000000000000000000000'

    # Try to download w/ nonexistent ticket
    r = as_admin.get('/download', params={'ticket': missing_object_id})
    assert r.status_code == 404

    # Retrieve a ticket for a batch download
    r = as_admin.post('/download', json={
        'optional': False,
        'filters': [{'tags': {
            '-': ['minus'],
            '+': ['plus']
        }}],
        'nodes': [
            {'level': 'project', '_id': project},
            {'level': 'session', '_id': session},
            {'level': 'acquisition', '_id': acquisition},
        ]
    })
    assert r.ok
    ticket = r.json()['ticket']

    # Perform the download
    r = as_admin.get('/download', params={'ticket': ticket})
    assert r.ok

    tar_file = cStringIO.StringIO(r.content)
    tar = tarfile.open(mode="r", fileobj=tar_file)

    # Verify a single file in tar with correct file name
    for tarinfo in tar:
        assert os.path.basename(tarinfo.name) == file_name
    tar.close()

    # Try to perform the download from a different IP
    update_result = api_db.downloads.update_one(
        {'_id': ticket},
        {'$set': {'ip': '0.0.0.0'}})
    assert update_result.modified_count == 1

    r = as_admin.get('/download', params={'ticket': ticket})
    assert r.status_code == 400

    # Try to retrieve a ticket referencing nonexistent containers
    r = as_admin.post('/download', json={
        'optional': False,
        'nodes': [
            {'level': 'project', '_id': missing_object_id},
            {'level': 'session', '_id': missing_object_id},
            {'level': 'acquisition', '_id': missing_object_id},
        ]
    })
    assert r.status_code == 404

    # Try to retrieve ticket for bulk download w/ invalid container name
    # (not project|session|acquisition)
    r = as_admin.post('/download', params={'bulk': 'true'}, json={
        'files': [{'container_name': 'subject', 'container_id': missing_object_id, 'filename': 'nosuch.csv'}]
    })
    assert r.status_code == 400

    # Try to retrieve ticket for bulk download referencing nonexistent file
    r = as_admin.post('/download', params={'bulk': 'true'}, json={
        'files': [{'container_name': 'project', 'container_id': project, 'filename': 'nosuch.csv'}]
    })
    assert r.status_code == 404

    # Retrieve ticket for bulk download
    r = as_admin.post('/download', params={'bulk': 'true'}, json={
        'files': [{'container_name': 'project', 'container_id': project, 'filename': file_name}]
    })
    assert r.ok
    ticket = r.json()['ticket']

    # Perform the download using symlinks
    r = as_admin.get('/download', params={'ticket': ticket, 'symlinks': 'true'})
    assert r.ok


def test_filelist_download(data_builder, file_form, as_admin):
    session = data_builder.create_session()
    zip_cont = cStringIO.StringIO()
    with zipfile.ZipFile(zip_cont, 'w') as zip_file:
        zip_file.writestr('two.csv', 'sample\ndata\n')
    zip_cont.seek(0)
    session_files = '/sessions/' + session + '/files'
    as_admin.post(session_files, files=file_form('one.csv'))
    as_admin.post(session_files, files=file_form(('two.zip', zip_cont)))

    # try to get non-existent file
    r = as_admin.get(session_files + '/non-existent.csv')
    assert r.status_code == 404

    # try to get file w/ non-matching hash
    r = as_admin.get(session_files + '/one.csv', params={'hash': 'match me if you can'})
    assert r.status_code == 409

    # get download ticket for single file
    r = as_admin.get(session_files + '/one.csv', params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download single file w/ ticket
    r = as_admin.get(session_files + '/one.csv', params={'ticket': ticket})
    assert r.ok

    # try to get zip info for non-zip file
    r = as_admin.get(session_files + '/one.csv', params={'ticket': ticket, 'info': 'true'})
    assert r.status_code == 400

    # try to get zip member of non-zip file
    r = as_admin.get(session_files + '/one.csv', params={'ticket': ticket, 'member': 'hardly'})
    assert r.status_code == 400

    # try to download a different file w/ ticket
    r = as_admin.get(session_files + '/two.zip', params={'ticket': ticket})
    assert r.status_code == 400

    # get download ticket for zip file
    r = as_admin.get(session_files + '/two.zip', params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # get zip info
    r = as_admin.get(session_files + '/two.zip', params={'ticket': ticket, 'info': 'true'})
    assert r.ok

    # try to get non-existent zip member
    r = as_admin.get(session_files + '/two.zip', params={'ticket': ticket, 'member': 'hardly'})
    assert r.status_code == 400

    # get zip member
    r = as_admin.get(session_files + '/two.zip', params={'ticket': ticket, 'member': 'two.csv'})
    assert r.ok


def test_analysis_download(data_builder, file_form, as_admin):
    session = data_builder.create_session()
    zip_cont = cStringIO.StringIO()
    with zipfile.ZipFile(zip_cont, 'w') as zip_file:
        zip_file.writestr('two.csv', 'sample\ndata\n')
    zip_cont.seek(0)
    analysis = as_admin.post('/sessions/' + session + '/analyses', files=file_form(
        'one.csv', ('two.zip', zip_cont),
        meta={'label': 'test', 'inputs': [{'name': 'one.csv'}, {'name': 'two.csv'}]}
    )).json()['_id']
    analysis_files = '/sessions/' + session + '/analyses/' + analysis + '/files'

    # try to download analysis files w/ non-existent ticket
    r = as_admin.get(analysis_files, params={'ticket': '000000000000000000000000'})
    assert r.status_code == 404

    # get analysis batch download ticket for all files
    r = as_admin.get(analysis_files, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # batch download analysis files w/ ticket
    r = as_admin.get(analysis_files, params={'ticket': ticket})
    assert r.ok

    # try to get download ticket for non-existent analysis file
    r = as_admin.get(analysis_files + '/non-existent.csv')
    assert r.status_code == 404

    # get analysis download ticket for single file
    r = as_admin.get(analysis_files + '/one.csv', params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download single analysis file w/ ticket
    r = as_admin.get(analysis_files + '/one.csv', params={'ticket': ticket})
    assert r.ok

    # try to get zip info for non-zip file
    r = as_admin.get(analysis_files + '/one.csv', params={'ticket': ticket, 'info': 'true'})
    assert r.status_code == 400

    # try to get zip member of non-zip file
    r = as_admin.get(analysis_files + '/one.csv', params={'ticket': ticket, 'member': 'nosuch'})
    assert r.status_code == 400

    # try to download a different file w/ ticket
    r = as_admin.get(analysis_files + '/two.zip', params={'ticket': ticket})
    assert r.status_code == 400

    # get analysis download ticket for zip file
    r = as_admin.get(analysis_files + '/two.zip', params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # get zip info
    r = as_admin.get(analysis_files + '/two.zip', params={'ticket': ticket, 'info': 'true'})
    assert r.ok

    # try to get non-existent zip member
    r = as_admin.get(analysis_files + '/two.zip', params={'ticket': ticket, 'member': 'nosuch'})
    assert r.status_code == 400

    # get zip member
    r = as_admin.get(analysis_files + '/two.zip', params={'ticket': ticket, 'member': 'two.csv'})
    assert r.ok
