def test_permissions(data_builder, as_admin):
    project = data_builder.create_project()
    user_1 = data_builder.create_user(_id='test-permissions-1@user.com')
    user_2 = data_builder.create_user(_id='test-permissions-2@user.com')

    permissions_path = '/projects/' + project + '/permissions'
    user_1_path = permissions_path + '/' + user_1
    user_2_path = permissions_path + '/' + user_2

    # GET is not allowed for general permissions path
    r = as_admin.get(permissions_path)
    assert r.status_code == 405

    # Add permissions for user 1
    r = as_admin.post(permissions_path, json={
        '_id': user_1,
        'access': 'ro',
        'phi-access': True
    })
    assert r.ok

    # Verify permissions for user 1
    r = as_admin.get(user_1_path)
    assert r.ok
    perms = r.json()
    assert perms['_id'] == user_1
    assert perms['access'] == 'ro'

    # Update user 1 to have admin access
    r = as_admin.put(user_1_path, json={'access': 'admin'})
    assert r.ok

    # Add user 2 to have ro access
    r = as_admin.post(permissions_path, json={
        '_id': user_2,
        'access': 'ro',
        'phi-access': True
    })
    assert r.ok

    # Attempt to change user 2's id to user 1
    r = as_admin.put(user_2_path, json={'_id': user_1})
    assert r.status_code == 404

    # Delete user 2
    r = as_admin.delete(user_2_path)
    assert r.ok

    # Ensure user 2 is gone
    r = as_admin.get(user_2_path)
    assert r.status_code == 404

def test_group_permissions(data_builder, as_admin, as_public):
    # Test permissions for groups
    api_key = '4hOn5aBx/nUiI0blDbTUPpKQsEbEn74rH9z5KctlXw6GrMKdicPGXKQg'
    user = data_builder.create_user(api_key=api_key)
    group = data_builder.create_group()

    as_other_user = as_public
    as_other_user.headers.update({'Authorization': 'scitran-user ' + api_key})

    permissions_path = '/groups/' + group + '/permissions'
    local_user_permissions_path = permissions_path + '/' + user
    admin_user_permissions_path = permissions_path + '/' + as_admin.get('/users/self').json()['_id']

    # Cannot retrieve permissions that don't exist
    r = as_admin.get(local_user_permissions_path)
    assert r.status_code == 404

    # Create permission for user
    r = as_admin.post(permissions_path, json={'_id': user, 'access': 'rw', 'phi-access': True})
    assert r.ok

    # Verify new user permission
    r = as_admin.get(local_user_permissions_path)
    assert r.ok
    permission = r.json()
    assert permission['_id'] == user
    assert permission['access'] == 'rw'

    # 'rw' users cannot access other user permissions
    r = as_other_user.get(admin_user_permissions_path)
    assert r.status_code == 403

    # Upgrade user to admin
    r = as_admin.put(local_user_permissions_path, json={'access': 'admin'})
    assert r.ok

    # User should now be able to access other permissions
    r = as_other_user.get(admin_user_permissions_path)
    assert r.ok

    # Change user back to 'rw' access
    r = as_admin.put(local_user_permissions_path, json={'access': 'rw'})
    assert r.ok

    # User is now forbidden again
    r = as_other_user.get(admin_user_permissions_path)
    assert r.status_code == 403

    # Delete permission
    r = as_admin.delete(local_user_permissions_path)
    assert r.ok

    # Verify delete
    r = as_admin.get(local_user_permissions_path)
    assert r.status_code == 404
