def test_batch(data_builder, as_user, as_admin):
    gear = data_builder.create_gear()
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
    batch_id = r.json()['_id']

    # create a batch w/ acquisition target and target_context
    r = as_admin.post('/batch', json={
        'gear_id': gear,
        'targets': [{'type': 'acquisition', 'id': acquisition}],
        'target_context': {'type': 'session', 'id': session}
    })
    assert r.ok
    batch_id = r.json()['_id']

    # get batch
    r = as_admin.get('/batch/' + batch_id)
    assert r.ok
    assert r.json()['state'] == 'pending'

    # try to cancel non-launched batch
    r = as_admin.post('/batch/' + batch_id + '/cancel')
    assert r.status_code == 400

    # run batch
    r = as_admin.post('/batch/' + batch_id + '/run')
    assert r.ok
    r = as_admin.get('/batch/' + batch_id)
    assert r.json()['state'] == 'launched'

    # try to run non-pending batch
    r = as_admin.post('/batch/' + batch_id + '/run')
    assert r.status_code == 400

    # cancel batch
    r = as_admin.post('/batch/' + batch_id + '/cancel')
    assert r.ok
    r = as_admin.get('/batch/' + batch_id)
    assert r.json()['state'] == 'cancelled'
