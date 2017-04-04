def test_extra_param(as_admin):
    label = 'extra_param'

    r = as_admin.post('/projects', json={
        'group': 'unknown',
        'label': label,
        'public': False,
        'extra_param': 'some_value'
    })
    assert r.status_code == 400

    r = as_admin.get('/projects')
    assert r.ok
    assert not any(project['label'] == label for project in r.json())
