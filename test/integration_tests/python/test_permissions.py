def test_permissions(data_builder, as_admin):
    project = data_builder.create_project()
    user_1 = data_builder.create_user(_id='test-permissions-1@user.com')
    user_2 = data_builder.create_user(_id='test-permissions-2@user.com')

    permissions_path = '/projects/' + project + '/permissions'
    user_1_local_path = permissions_path + '/local/' + user_1
    user_2_local_path = permissions_path + '/local/' + user_2
    user_2_another_path = permissions_path + '/another/' + user_2

    # GET is not allowed for general permissions path
    r = as_admin.get(permissions_path)
    assert r.status_code == 405

    # Add permissions for user 1
    r = as_admin.post(permissions_path, json={
        '_id': user_1,
        'site': 'local',
        'access': 'ro'
    })
    assert r.ok

    # Verify permissions for user 1
    r = as_admin.get(user_1_local_path)
    assert r.ok
    perms = r.json()
    assert perms['_id'] == user_1
    assert perms['site'] == 'local'
    assert perms['access'] == 'ro'

    # Update user 1 to have admin access
    r = as_admin.put(user_1_local_path, json={'access': 'admin'})
    assert r.ok

    # Add user 2 to have ro access
    r = as_admin.post(permissions_path, json={
        '_id': user_2,
        'site': 'local',
        'access': 'ro'
    })
    assert r.ok

    # Attempt to change user 2's id to user 1
    r = as_admin.put(user_2_local_path, json={'_id': user_1})
    assert r.status_code == 404

    # Change user 2's site
    r = as_admin.put(user_2_local_path, json={'site': 'another'})
    assert r.ok

    # Verify user 2's site changed
    r = as_admin.get(user_2_another_path)
    assert r.ok
    perms = r.json()
    assert perms['_id'] == user_2
    assert perms['site'] == 'another'
    assert perms['access'] == 'ro'

    # Delete user 2
    r = as_admin.delete(user_2_another_path)
    assert r.ok

    # Ensure user 2 is gone
    r = as_admin.get(user_2_another_path)
    assert r.status_code == 404
