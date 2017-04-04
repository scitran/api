import cStringIO
import os
import tarfile


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
