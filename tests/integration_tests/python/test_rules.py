def test_site_rules(randstr, data_builder, as_admin, as_user, as_public):
    gear_name = randstr()
    gear = data_builder.create_gear(gear={'name': gear_name, 'version': '0.0.1'})

    gear_2_name = randstr()
    gear_2 = data_builder.create_gear(gear={'name': gear_2_name, 'version': '0.0.1'})

    rule = {
        'alg': gear_name,
        'name': 'csv-job-trigger-rule',
        'any': [],
        'all': [
            {'type': 'file.type', 'value': 'tabular data'},
        ]
    }

    # GET ALL
    # attempt to get site rules without login
    r = as_public.get('/site/rules')
    assert r.status_code == 403

    # get empty list of site rules
    r = as_admin.get('/site/rules')
    assert r.ok
    assert r.json() == []


    # POST
    # attempt to add site rule without admin
    r = as_user.post('/site/rules', json=rule)
    assert r.status_code == 403

    # attempt to add site rule with empty payload
    r = as_admin.post('/site/rules', json={})
    assert r.status_code == 400
    assert 'Empty Payload' in r.json()['message']

    # attempt to add site rule with invalid regex
    invalid_pattern = '^(?non-image$).+'
    r = as_admin.post('/site/rules', json={
        'alg': gear_name,
        'name': 'invalid-regex-rule',
        'any': [],
        'all': [
            {'type': 'file.measurements', 'value': invalid_pattern, 'regex': True},
        ]
    })
    assert r.status_code == 422
    assert invalid_pattern in r.json()['patterns']

    # add site rule
    r = as_admin.post('/site/rules', json=rule)
    assert r.ok
    rule_id = r.json()['_id']

    r = as_admin.get('/site/rules')
    assert r.ok
    assert len(r.json()) == 1

    # GET ALL
    # attempt to get site rules without login
    r = as_public.get('/site/rules')
    assert r.status_code == 403

    # test rule is returned in list
    r = as_admin.get('/site/rules')
    assert r.ok
    assert r.json()[0]['_id'] == rule_id


    # GET ONE
    # attempt to get specific site rule without login
    r = as_public.get('/site/rules/' + rule_id)
    assert r.status_code == 403

    # attempt to get non-existent site rule
    r = as_admin.get('/site/rules/000000000000000000000000')
    assert r.status_code == 404

    # get specific site rule
    r = as_admin.get('/site/rules/' + rule_id)
    assert r.ok
    assert r.json()['alg'] == gear_name


    # PUT
    update = {'alg': gear_2_name}

    # attempt to modify site rule without admin
    r = as_user.put('/site/rules/' + rule_id, json=update)
    assert r.status_code == 403

    # attempt to modify non-existent site rule
    r = as_admin.put('/site/rules/000000000000000000000000', json=update)
    assert r.status_code == 404

    # attempt to modify site rule with empty payload
    r = as_admin.put('/site/rules/' + rule_id, json={})
    assert r.status_code == 400

    # attempt to modify site rule with invalid regex
    r = as_admin.put('/site/rules/' + rule_id, json={
        'all': [
            {'type': 'file.measurements', 'value': invalid_pattern, 'regex': True},
        ]
    })
    assert r.status_code == 422
    assert invalid_pattern in r.json()['patterns']

    # modify site rule
    r = as_admin.put('/site/rules/' + rule_id, json=update)
    assert r.ok
    r = as_admin.get('/site/rules/' + rule_id)
    assert r.ok
    assert r.json()['alg'] == gear_2_name


    # DELETE
    # attempt to delete rule without admin
    r = as_user.delete('/site/rules/' + rule_id)
    assert r.status_code == 403

    # attempt to delete non-existent site rule
    r = as_admin.delete('/site/rules/000000000000000000000000')
    assert r.status_code == 404

    # delete site rule
    r = as_admin.delete('/site/rules/' + rule_id)
    assert r.ok

    r = as_admin.get('/site/rules/' + rule_id)
    assert r.status_code == 404


def test_site_rules_copied_to_new_projects(randstr, data_builder, file_form, as_admin, as_root):
    gear_1_name = randstr()
    gear_1 = data_builder.create_gear(gear={'name': gear_1_name, 'version': '0.0.1'})

    rule_1 = {
        'alg': gear_1_name,
        'name': 'csv-job-trigger-rule',
        'any': [],
        'all': [
            {'type': 'file.type', 'value': 'tabular data'},
        ]
    }

    gear_2_name = randstr()
    gear_2 = data_builder.create_gear(gear={'name': gear_2_name, 'version': '0.0.1'})

    rule_2 = {
        'alg': gear_2_name,
        'name': 'text-job-trigger-rule',
        'any': [],
        'all': [
            {'type': 'file.type', 'value': 'text'},
        ]
    }

    # Add rules to site level
    r = as_admin.post('/site/rules', json=rule_1)
    assert r.ok
    rule_id_1 = r.json()['_id']

    r = as_admin.post('/site/rules', json=rule_2)
    assert r.ok
    rule_id_2 = r.json()['_id']

    # Ensure rules exist
    r = as_admin.get('/site/rules')
    assert r.ok
    assert len(r.json()) == 2


    # Create new project via POST
    group = data_builder.create_group()
    r = as_admin.post('/projects', json={
        'group': group,
        'label': 'project_1'
    })
    assert r.ok
    project_id = r.json()['_id']

    r = as_admin.get('/projects/'+project_id+'/rules')
    assert r.ok
    assert len(r.json()) == 2

    # Create new project via upload
    r = as_admin.post('/upload/label', files=file_form(
        'acquisition.csv',
        meta={
            'group': {'_id': group},
            'project': {
                'label': 'test_project',
            },
            'session': {
                'label': 'test_session_label',
                'subject': {
                    'code': 'test_subject_code'
                },
            },
            'acquisition': {
                'label': 'test_acquisition_label',
                'files': [{'name': 'acquisition.csv'}]
            }
        })
    )
    assert r.ok

    # Find newly created project id
    projects = as_root.get('/projects').json()
    for p in projects:
        if p['label'] == 'test_project':
            project_2 = p['_id']
            break

    assert project_2
    r = as_admin.get('/projects/'+project_2+'/rules')
    assert r.ok
    assert len(r.json()) == 2

    # Cleanup site rules
    r = as_admin.delete('/site/rules/' + rule_id_1)
    assert r.ok
    r = as_admin.delete('/site/rules/' + rule_id_2)
    assert r.ok

    # delete group and children recursively (created by upload)
    data_builder.delete_group(group, recursive=True)


def test_rules(randstr, data_builder, file_form, as_root, as_admin, with_user, api_db):
    # create versioned gear to cover code selecting latest gear
    gear_name = randstr()
    gear_1 = data_builder.create_gear(gear={'name': gear_name, 'version': '0.0.1'})
    gear_2 = data_builder.create_gear(gear={'name': gear_name, 'version': '0.0.2'})
    project = data_builder.create_project()

    bad_payload = {'test': 'rules'}

    # try to get all project rules of non-existent project
    r = as_admin.get('/projects/000000000000000000000000/rules')
    assert r.status_code == 404

    # try to get single project rule of non-existent project
    r = as_admin.get('/projects/000000000000000000000000/rules/000000000000000000000000')
    assert r.status_code == 404

    # try to get project rules w/o permissions
    r = with_user.session.get('/projects/' + project + '/rules')
    assert r.status_code == 403

    # get project rules (yet empty list)
    r = as_admin.get('/projects/' + project + '/rules')
    assert r.ok
    assert r.json() == []

    # upload file w/o any rules
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test1.csv'))
    assert r.ok

    # try to add rule to non-existent project
    r = as_admin.post('/projects/000000000000000000000000/rules', json=bad_payload)
    assert r.status_code == 404

    # add read-only perms for user
    r = as_admin.post('/projects/' + project + '/permissions', json={
        '_id': with_user.user, 'access': 'ro', 'phi-access': True})
    assert r.ok

    # try to add rule w/ read-only project perms
    r = with_user.session.post('/projects/' + project + '/rules', json=bad_payload)
    assert r.status_code == 403

    rule_json = {
        'alg': 'non-existent-gear-name',
        'name': 'csv-job-trigger-rule',
        'any': [],
        'all': [
            {'type': 'file.type', 'value': 'tabular data'},
        ]
    }

    # try to add project rule w/ non-existent gear
    # NOTE this is a legacy rule
    r = as_admin.post('/projects/' + project + '/rules', json=rule_json)
    assert r.status_code == 400

    # add project rule w/ proper gear alg
    # NOTE this is a legacy rule
    rule_json['alg'] = gear_name
    r = as_admin.post('/projects/' + project + '/rules', json=rule_json)
    assert r.ok
    rule = r.json()['_id']

    # get project rules (verify rule was added)
    r = as_admin.get('/projects/' + project + '/rules')
    assert r.ok
    assert r.json()[0]['alg'] == gear_name

    # try to get single project rule using non-existent rule id
    r = as_admin.get('/projects/' + project + '/rules/000000000000000000000000')
    assert r.status_code == 404

    # try to update rule of non-existent project
    r = as_admin.put('/projects/000000000000000000000000/rules/000000000000000000000000', json=bad_payload)
    assert r.status_code == 404

    # try to update non-existent rule
    r = as_admin.put('/projects/' + project + '/rules/000000000000000000000000', json=bad_payload)
    assert r.status_code == 404

    # try to update rule w/ read-only project perms
    r = with_user.session.put('/projects/' + project + '/rules/' + rule, json={'alg': gear_name})
    assert r.status_code == 403

    # try to update rule to with invalid gear alg
    r = as_admin.put('/projects/' + project + '/rules/' + rule, json={'alg': 'not-a-real-gear'})
    assert r.status_code == 400

    # update name of rule
    rule_name = 'improved-csv-trigger-rule'
    r = as_admin.put('/projects/' + project + '/rules/' + rule, json={'name': rule_name})
    assert r.ok

    # verify rule was updated
    r = as_admin.get('/projects/' + project + '/rules/' + rule)
    assert r.ok
    assert r.json()['name'] == rule_name

    # upload file that matches rule
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test2.csv'))
    assert r.ok

    # test that job was created via rule
    gear_jobs = [job for job in api_db.jobs.find({'gear_id': gear_2})]
    assert len(gear_jobs) == 1
    assert len(gear_jobs[0]['inputs']) == 1
    assert gear_jobs[0]['inputs'][0]['name'] == 'test2.csv'

    # try to delete rule of non-existent project
    r = as_admin.delete('/projects/000000000000000000000000/rules/000000000000000000000000')
    assert r.status_code == 404

    # try to delete non-existent rule
    r = as_admin.delete('/projects/' + project + '/rules/000000000000000000000000')
    assert r.status_code == 404

    # try to delete rule w/ read-only project perms
    r = with_user.session.delete('/projects/' + project + '/rules/' + rule)
    assert r.status_code == 403

    # delete rule
    r = as_admin.delete('/projects/' + project + '/rules/' + rule)
    assert r.ok


    # add valid container.has-<something> project rule
    # NOTE this is a legacy rule
    r = as_admin.post('/projects/' + project + '/rules', json={
        'alg': gear_name,
        'name': 'txt-job-trigger-rule-with-measurement',
        'any': [
            {'type': 'container.has-measurement', 'value': 'functional'},
            {'type': 'container.has-measurement', 'value': 'anatomical'}
        ],
        'all': [
            {'type': 'file.type', 'value': 'text'},
        ]
    })
    assert r.ok
    rule2 = r.json()['_id']

    # upload file that matches only part of rule
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test3.txt'))
    assert r.ok

    # test that job was not created via rule
    gear_jobs = [job for job in api_db.jobs.find({'gear_id': gear_2})]
    assert len(gear_jobs) == 1 # still 1 from before

    # update test2.csv's metadata to include a valid measurement to spawn job
    metadata = {
        'project':{
            'label': 'rule project',
            'files': [
                {
                    'name': 'test2.csv',
                    'measurements': ['functional']
                }
            ]
        }
    }

    r = as_root.post('/engine',
        params={'level': 'project', 'id': project},
        files=file_form(meta=metadata)
    )
    assert r.ok

    # Ensure file without type or measurements does not cause issues with rule evalution
    # upload file that matches only part of rule
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test3.notreal'))
    assert r.ok

    # test that only one job was created via rule
    gear_jobs = [job for job in api_db.jobs.find({'gear_id': gear_2})]
    assert len(gear_jobs) == 2
    assert len(gear_jobs[1]['inputs']) == 1
    assert gear_jobs[1]['inputs'][0]['name'] == 'test3.txt'

    # delete rule
    r = as_admin.delete('/projects/' + project + '/rules/' + rule2)
    assert r.ok

    # add regex rule
    # NOTE this is a legacy rule
    r = as_admin.post('/projects/' + project + '/rules', json={
        'alg': gear_name,
        'name': 'file-measurement-regex',
        'any': [],
        'all': [
            {'type': 'file.name', 'value': 'test\d+\.(csv|txt)', 'regex': True},
        ]
    })
    assert r.ok
    rule3 = r.json()['_id']

    # upload file matching regex rule
    r = as_admin.post('/projects/' + project + '/files', files=file_form('test999.txt'))
    assert r.ok

    # test that job was created via regex rule
    gear_jobs = [job for job in api_db.jobs.find({'gear_id': gear_2})]
    assert len(gear_jobs) == 3

    # delete rule
    r = as_admin.delete('/projects/' + project + '/rules/' + rule3)
    assert r.ok

    # TODO add and test 'new-style' rules
