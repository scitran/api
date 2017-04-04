def test_groups(as_admin, data_builder):
    # Cannot find a non-existant group
    r = as_admin.get('/groups/non-existent')
    assert r.status_code == 404

    group = data_builder.create_group()

    # Able to find new group
    r = as_admin.get('/groups/' + group)
    assert r.ok

    # Able to change group name
    group_name = 'New group name'
    r = as_admin.put('/groups/' + group, json={'name': group_name})
    assert r.ok

    r = as_admin.get('/groups/' + group)
    assert r.ok
    assert r.json()['name'] == group_name
