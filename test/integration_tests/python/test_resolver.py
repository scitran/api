def test_resolver(data_builder, as_admin, as_public):
    # try accessing resolver w/o logging in
    r = as_public.post('/resolve', json={'path': []})
    assert r.status_code == 403

    # try resolving invalid (non-list) path
    r = as_admin.post('/resolve', json={'path': 'test'})
    assert r.status_code == 500

    # resolve root
    r = as_admin.post('/resolve', json={'path': []})
    assert r.ok
    assert r.json()['path'] == []

    # resolve root w/ group
    group = data_builder.create_group()
    r = as_admin.post('/resolve', json={'path': []})
    result = r.json()
    assert r.ok
    assert result['path'] == []
    assert sum(child['_id'] == group for child in result['children']) == 1
    assert all(child['node_type'] == 'group' for child in result['children'])

    # try to resolve non-existent group id
    r = as_admin.post('/resolve', json={'path': ['non-existent-group-id']})
    assert r.status_code == 500

    # resolve group
    r = as_admin.post('/resolve', json={'path': [group]})
    result = r.json()
    assert r.ok
    assert [node['_id'] for node in result['path']] == [group]
    assert result['children'] == []

    # resolve group w/ project
    project_label = 'test-resolver-project-label'
    project = data_builder.create_project(label=project_label)
    r = as_admin.post('/resolve', json={'path': [group]})
    result = r.json()
    assert r.ok
    assert [node['_id'] for node in result['path']] == [group]
    assert sum(child['_id'] == project for child in result['children']) == 1
    assert all(child['node_type'] == 'project' for child in result['children'])

    # try to resolve non-existent project label
    r = as_admin.post('/resolve', json={'path': [group, 'non-existent-project-label']})
    assert r.status_code == 500

    # resolve project
    r = as_admin.post('/resolve', json={'path': [group, project_label]})
    result = r.json()
    assert r.ok
    assert [node['_id'] for node in result['path']] == [group, project]
    assert result['children'] == []

    # resolve project w/ session
    session_label = 'test-resolver-session-label'
    session = data_builder.create_session(label=session_label)
    r = as_admin.post('/resolve', json={'path': [group, project_label]})
    result = r.json()
    assert r.ok
    assert [node['_id'] for node in result['path']] == [group, project]
    assert sum(child['_id'] == session for child in result['children']) == 1
    assert all(child['node_type'] == 'session' for child in result['children'])
