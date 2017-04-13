def test_rules(randstr, data_builder, file_form, as_root, as_admin, as_user):
    # create versioned gear to cover code selecting latest gear
    gear_name = randstr()
    gear_1 = data_builder.create_gear(gear={'name': gear_name, 'version': '0.0.1'})
    gear_2 = data_builder.create_gear(gear={'name': gear_name, 'version': '0.0.2'})
    project = data_builder.create_project()

    # try to get project rules of non-existent project
    r = as_admin.get('/projects/000000000000000000000000/rules')
    assert r.status_code == 404

    # try to get project rules w/o permissions
    r = as_user.get('/projects/' + project + '/rules')
    assert r.status_code == 404

    # get project rules (yet empty list)
    r = as_admin.get('/projects/' + project + '/rules')
    assert r.ok
    assert r.json() == []

    # upload file w/o any rules
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test1.csv'))
    assert r.ok

    # add invalid project rule w/ non-existent gear
    # NOTE this is a legacy rule
    r = as_admin.post('/projects/' + project + '/rules', json={
        'alg': 'non-existent-gear-name',
        'name': 'csv-job-trigger-rule',
        'any': [],
        'all': [
            {'type': 'file.type', 'value': 'tabular data'},
        ]
    })
    assert r.ok
    rule = r.json()['_id']

    # verify rule was added
    r = as_admin.get('/projects/' + project + '/rules')
    assert r.ok
    assert r.json()[0]['alg'] == 'non-existent-gear-name'

    # try to upload file that matches invalid rule (500, Unknown gear)
    # NOTE with an invalid and some valid rules an upload could conceivably return
    #      a 500 after already having created jobs for the valid rules
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test.csv'))
    assert r.status_code == 500

    # update rule to use a valid gear
    r = as_admin.put('/projects/' + project + '/rules/' + rule, json={'alg': gear_name})
    assert r.ok

    # verify rule was updated
    r = as_admin.get('/projects/' + project + '/rules/' + rule)
    assert r.ok
    assert r.json()['alg'] == gear_name

    # upload file that matches rule
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test2.csv'))
    assert r.ok

    # test that job was created via rule
    jobs = as_root.get('/jobs').json()
    gear_jobs = [job for job in jobs if job['gear_id'] == gear_2]
    assert len(gear_jobs) == 1
    assert len(gear_jobs[0]['inputs']) == 1
    assert gear_jobs[0]['inputs'][0]['name'] == 'test2.csv'

    # TODO add and test 'new-style' rules
