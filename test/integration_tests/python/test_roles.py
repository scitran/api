def test_roles(data_builder, as_admin, as_public):
    api_key = '4hOn5aBx/nUiI0blDbTUPpKQsEbEn74rH9z5KctlXw6GrMKdicPGXKQg'
    user = data_builder.create_user(api_key=api_key)
    group = data_builder.create_group()

    as_other_user = as_public
    as_other_user.headers.update({'Authorization': 'scitran-user ' + api_key})

    roles_path = '/groups/' + group + '/roles'
    local_user_roles_path = roles_path + '/local/' + user
    admin_user_roles_path = roles_path + '/local/' + as_admin.get('/users/self').json()['_id']

    # Cannot retrieve roles that don't exist
    r = as_admin.get(local_user_roles_path)
    assert r.status_code == 404

    # Create role for user
    r = as_admin.post(roles_path, json={'_id': user, 'site': 'local', 'access': 'rw'})
    assert r.ok

    # Verify new user role
    r = as_admin.get(local_user_roles_path)
    assert r.ok
    role = r.json()
    assert role['_id'] == user
    assert role['access'] == 'rw'

    # 'rw' users cannot access other user roles
    r = as_other_user.get(admin_user_roles_path)
    assert r.status_code == 403

    # Upgrade user to admin
    r = as_admin.put(local_user_roles_path, json={'access': 'admin'})
    assert r.ok

    # User should now be able to access other roles
    r = as_other_user.get(admin_user_roles_path)
    assert r.ok

    # Change user back to 'rw' access
    r = as_admin.put(local_user_roles_path, json={'access': 'rw'})
    assert r.ok

    # User is now forbidden again
    r = as_other_user.get(admin_user_roles_path)
    assert r.status_code == 403

    # Delete role
    r = as_admin.delete(local_user_roles_path)
    assert r.ok

    # Verify delete
    r = as_admin.get(local_user_roles_path)
    assert r.status_code == 404
