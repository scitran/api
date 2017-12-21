from dateutil.parser import parse

def test_groups(as_user, as_admin, data_builder):
    # Cannot find a non-existant group
    r = as_admin.get('/groups/non-existent')
    assert r.status_code == 404

    group = data_builder.create_group()

    # Able to find new group
    r = as_admin.get('/groups/' + group)
    assert r.ok
    assert r.json()['label'] != None
    first_modified = r.json()['modified']

    # Test to make sure that list of roles nor name exists in a newly created group
    r = as_admin.get('/groups/' + group)
    assert r.json().get('roles', 'No Roles') == 'No Roles'
    assert r.json().get('name', 'No Name') == 'No Name'

    # Able to change group label
    group_label = 'New group label'
    r = as_admin.put('/groups/' + group, json={'label': group_label})
    assert r.ok

    # Get the group again to compare timestamps
    r = as_admin.get('/groups/' + group)
    assert r.ok
    second_modified = r.json()['modified']
    d1 = parse(first_modified)
    d2 = parse(second_modified)
    assert d2 > d1

    # Add a tag to the group
    tag_name = 'Grey2'
    r = as_admin.post('/groups/' + group + '/tags', json={'value': tag_name})
    assert r.ok

    # Get the group again to compare timestamps for the Add tag test groups
    r = as_admin.get('/groups/' + group)
    assert r.ok
    third_modified = r.json()['modified']
    d3 = parse(third_modified)
    assert d3 > d2

    # Edit the tag
    new_tag_name = 'Brown'
    r = as_admin.put('/groups/' + group + '/tags/' + tag_name, json={'value': new_tag_name})
    assert r.ok

    # Get the group again to compare timestamps for the Edit tag test groups
    r = as_admin.get('/groups/' + group)
    assert r.ok
    fourth_modified = r.json()['modified']
    d4 = parse(fourth_modified)
    assert d4 > d3

    # Delete the tag
    r = as_admin.delete('/groups/' + group + '/tags/' + new_tag_name)
    assert r.ok

    # Get the group again to compare timestamps for the Delete tag test groups
    r = as_admin.get('/groups/' + group)
    assert r.ok
    fith_modified = r.json()['modified']
    d5 = parse(fith_modified)
    assert d5 > d4

    # Add a permission to the group
    user = {'access': 'rw', '_id': 'newUser@fakeuser.com', 'phi-access': True}
    r = as_admin.post('/groups/' + group + '/permissions', json=user)
    assert r.ok

    # Get the group again to compare timestamps for the Add permission test groups
    r = as_admin.get('/groups/' + group)
    assert r.ok
    six_modified = r.json()['modified']
    d6 = parse(six_modified)
    assert d6 > d5

    # Edit a permission in the group
    user = {'access': 'ro', '_id': 'newUser@fakeuser.com'}
    r = as_admin.put('/groups/' + group + '/permissions/' + user['_id'], json=user)
    assert r.ok

    # Get all permissions for each group
    r = as_admin.get('/users/admin@user.com/groups')
    assert r.ok
    assert r.json()[0].get("permissions")[0].get("_id") == "admin@user.com"

    # Get the group again to compare timestamps for the Edit permission test groups
    r = as_admin.get('/groups/' + group)
    assert r.ok
    seven_modified = r.json()['modified']
    d7 = parse(seven_modified)
    assert d7 > d6

    # Delete a permission in the group
    r = as_admin.delete('/groups/' + group + '/permissions/' + user['_id'])
    assert r.ok

    # Get the group again to compare timestamps for the Edit permission test groups
    r = as_admin.get('/groups/' + group)
    assert r.ok
    eight_modified = r.json()['modified']
    d8 = parse(eight_modified)
    assert d8 > d7

    group2 = data_builder.create_group()
    r = as_admin.post('/groups/' + group2 + '/permissions', json={'access':'admin','_id':'user@user.com', 'phi-access': True})
    assert r.ok
    r = as_user.get('/groups')
    assert r.ok
    assert len(r.json()) == 1
    assert r.json()[0].get('permissions', []) != []
    r = as_admin.get('/groups')
    assert r.ok
    assert len(r.json()) > 1

    # Empty put request should 400
    r = as_admin.put('/groups/' + group, json={})
    assert r.status_code == 400

    r = as_admin.get('/groups/' + group)
    assert r.ok
    assert r.json()['label'] == group_label

    # Test join=projects
    project = data_builder.create_project()
    r = as_admin.get('/groups', params={'join': 'projects'})
    assert r.ok
    assert r.json()[0].get('projects')[0].get('_id') == project
