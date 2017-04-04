def test_rule_access(data_builder, as_admin):
    project = data_builder.create_project()

    r = as_admin.get('/projects/' + project + '/rules')
    assert r.ok

    r = as_admin.post('/projects/' + project + '/rules', json={
        'alg': 'my-gear-name',

        'name': 'whatever',

        'any': [],

        'all': [
            {
                'type': 'file.type',
                'value': 'nifti'
            },
            {
                'type': 'file.measurements',
                'value': 'functional'
            }
        ]
    })
    assert r.ok

    r = as_admin.get('/projects/' + project + '/rules')
    assert r.ok
    assert r.json()[0]['alg'] == 'my-gear-name'
