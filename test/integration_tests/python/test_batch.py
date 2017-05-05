def test_batch(data_builder, as_user, as_admin, as_root):
    gear = data_builder.create_gear()
    analysis_gear = data_builder.create_gear(category='analysis')
    invalid_gear = data_builder.create_gear(gear={'custom': {'flywheel': {'invalid': True}}})

    empty_project = data_builder.create_project()
    project = data_builder.create_project()
    session = data_builder.create_session(project=project)
    acquisition = data_builder.create_acquisition(session=session)
    as_admin.post('/acquisitions/' + acquisition + '/files', files={
        'file': ('test.txt', 'test\ncontent\n')})

    # get all
    r = as_user.get('/batch')
    assert r.ok

    # get all w/o enforcing permissions
    r = as_admin.get('/batch')
    assert r.ok

    # get all as root
    r = as_root.get('/batch')
    assert r.ok

    # try to create batch without gear_id/targets
    r = as_admin.post('/batch', json={})
    assert r.status_code == 400

    # try to create batch with different target container types
    r = as_admin.post('/batch', json={
        'gear_id': gear,
        'targets': [
            {'type': 'session', 'id': 'test-session-id'},
            {'type': 'acquisition', 'id': 'test-acquisition-id'},
        ],
    })
    assert r.status_code == 400

    # try to create batch using an invalid gear
    r = as_admin.post('/batch', json={
        'gear_id': invalid_gear,
        'targets': [{'type': 'session', 'id': 'test-session-id'}],
    })
    assert r.status_code == 400

    # try to create batch for project w/o acquisitions
    r = as_admin.post('/batch', json={
        'gear_id': gear,
        'targets': [{'type': 'project', 'id': empty_project}]
    })
    assert r.status_code == 404

    # try to create batch w/o write permission
    r = as_user.post('/batch', json={
        'gear_id': gear,
        'targets': [{'type': 'project', 'id': project}]
    })
    assert r.status_code == 403

    # create a batch w/ session target
    r = as_admin.post('/batch', json={
        'gear_id': gear,
        'targets': [{'type': 'session', 'id': session}]
    })
    assert r.ok

    # create a batch w/ acquisition target and target_context
    r = as_admin.post('/batch', json={
        'gear_id': gear,
        'targets': [{'type': 'acquisition', 'id': acquisition}],
        'target_context': {'type': 'session', 'id': session}
    })
    assert r.ok
    batch_id = r.json()['_id']

    # create a batch w/ analysis gear
    r = as_admin.post('/batch', json={
        'gear_id': analysis_gear,
        'targets': [{'type': 'session', 'id': session}]
    })
    assert r.ok
    analysis_batch_id = r.json()['_id']

    # try to get non-existent batch
    r = as_admin.get('/batch/000000000000000000000000')
    assert r.status_code == 404

    # try to get batch w/o perms (different user)
    r = as_user.get('/batch/' + batch_id)
    assert r.status_code == 403

    # get batch
    r = as_admin.get('/batch/' + batch_id)
    assert r.ok
    assert r.json()['state'] == 'pending'

    # get batch w/ ?jobs=true
    r = as_admin.get('/batch/' + batch_id, params={'jobs': 'true'})
    assert r.ok
    assert 'jobs' in r.json()

    # try to cancel non-launched batch
    r = as_admin.post('/batch/' + batch_id + '/cancel')
    assert r.status_code == 400

    # run batch
    r = as_admin.post('/batch/' + batch_id + '/run')
    assert r.ok

    # test batch.state after calling run
    r = as_admin.get('/batch/' + batch_id)
    assert r.json()['state'] == 'launched'

    # try to run non-pending batch
    r = as_admin.post('/batch/' + batch_id + '/run')
    assert r.status_code == 400

    # cancel batch
    r = as_admin.post('/batch/' + batch_id + '/cancel')
    assert r.ok

    # test batch.state after calling cancel
    r = as_admin.get('/batch/' + batch_id)
    assert r.json()['state'] == 'cancelled'

    # run analysis batch
    r = as_admin.post('/batch/' + analysis_batch_id + '/run')
    assert r.ok
