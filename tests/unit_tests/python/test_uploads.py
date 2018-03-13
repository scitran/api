import requests_mock


def test_signed_url_reaper_upload(as_drone, mocker):

    payload = {
        "metadata": {
            "group": {"_id": "scitran"},
            "project": {"label": ""},
            "session": {
                "uid": "session_uid",
                "subject": {"code": "bela"}
            },
            "acquisition": {
                "uid": "acquisition_uid",
                "files": [{"name": "test"}]
            }
        },
        "filename": "test"
    }

    r = as_drone.post('/upload/reaper?ticket=',
                     json=payload)

    assert r.status_code == 405

    mock_fs = mocker.patch('api.upload.config.fs')
    mock_fs.get_signed_url.return_value = 'url'
    r = as_drone.post('/upload/reaper?ticket=',
                      json=payload)

    assert r.ok
    assert r.json['upload_url'] == 'url'

    ticket_id = r.json['ticket']

    r = as_drone.post('/upload/reaper?ticket=' + ticket_id)
    assert r.ok

    assert mock_fs.move.called


def test_signed_url_label_upload(as_drone, data_builder, mocker):
    group = data_builder.create_group()

    payload = {
        "metadata": {
            'group': {'_id': group},
            'project': {
                'label': 'test_project',
                'files': [{'name': 'project.csv'}]
            }
        },
        "filename": "project.csv"
    }

    r = as_drone.post('/upload/label?ticket=',
                     json=payload)

    assert r.status_code == 405

    mock_fs = mocker.patch('api.upload.config.fs')
    mock_fs.get_signed_url.return_value = 'url'
    r = as_drone.post('/upload/label?ticket=',
                      json=payload)

    assert r.ok
    assert r.json['upload_url'] == 'url'

    ticket_id = r.json['ticket']

    r = as_drone.post('/upload/label?ticket=' + ticket_id)
    assert r.ok

    assert mock_fs.move.called


def test_engine_upload(as_drone, data_builder, mocker):
    project = data_builder.create_project()

    payload = {
        'metadata': {
            'project': {
                'label': 'engine project',
                'info': {'test': 'p'},
                'files': [
                    {
                        'name': 'one.csv',
                        'type': 'engine type 0',
                        'info': {'test': 'f0'}
                    }
                ]
            }
        },
        'filename': 'one.csv'
    }

    r = as_drone.post('/engine?ticket=&level=%s&id=%s' % ('project', project),
                     json=payload)

    assert r.status_code == 405

    mock_fs = mocker.patch('api.upload.config.fs')
    mock_fs.get_signed_url.return_value = 'url'
    r = as_drone.post('/engine?ticket=&level=%s&id=%s' % ('project', project),
                      json=payload)

    assert r.ok
    assert r.json['upload_url'] == 'url'

    ticket_id = r.json['ticket']

    r = as_drone.post('/engine?ticket=%s&level=%s&id=%s' % (ticket_id, 'project', project))
    assert r.ok

    assert mock_fs.move.called


def test_filelisthandler_signed_url_upload(as_drone, data_builder, mocker):
    project = data_builder.create_project()

    payload = {
        'metadata': {},
        'filename': 'one.csv'
    }

    r = as_drone.post('/projects/' + project + '/files?ticket=', json=payload)
    assert  r.status_code == 405

    mock_fs = mocker.patch('api.upload.config.fs')
    mock_fs.get_signed_url.return_value = 'url'
    r = as_drone.post('/projects/' + project + '/files?ticket=', json=payload)

    assert r.ok
    assert r.json['upload_url'] == 'url'

    ticket_id = r.json['ticket']

    r = as_drone.post('/projects/' + project + '/files?ticket=' + ticket_id)
    assert r.ok

    assert mock_fs.move.called
