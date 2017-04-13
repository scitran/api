def test_users(as_root, as_user, as_public):
    # List users
    r = as_user.get('/users')
    assert r.ok

    # Try to get self w/o logging in
    r = as_public.get('/users/self')
    assert r.status_code == 400

    # Get self as user
    r = as_user.get('/users/self')
    assert r.ok
    user_id = r.json()['_id']

    # Get self as admin
    r = as_root.get('/users/self')
    assert r.ok
    admin_id = r.json()['_id']
    assert admin_id != user_id

    # Try to get self's avatar
    r = as_user.get('/users/self/avatar')
    assert r.status_code == 404

    # Get user as user
    r = as_user.get('/users/' + user_id)
    assert r.ok

    # Try to get user avatar as user
    r = as_user.get('/users/' + user_id + '/avatar')
    assert r.status_code == 404

    # Try adding new user missing required attr
    r = as_root.post('/users', json={
        '_id': 'jane.doe@gmail.com',
        'lastname': 'Doe',
        'email': 'jane.doe@gmail.com',
    })
    assert r.status_code == 400
    assert "'firstname' is a required property" in r.text

    # Add new user
    new_user_id = 'new@user.com'
    r = as_root.post('/users', json={
        '_id': new_user_id,
        'firstname': 'New',
        'lastname': 'User',
    })
    assert r.ok
    r = as_root.get('/users/' + new_user_id)
    assert r.ok

    # Try to update non-existent user
    r = as_root.put('/users/nonexistent@user.com', json={'firstname': 'Realname'})
    assert r.status_code == 404

    # Update existing user
    r = as_root.put('/users/' + new_user_id, json={'firstname': 'Realname'})
    assert r.ok
    assert r.json()['modified'] == 1

    # Try to delete non-existent user
    r = as_root.delete('/users/nonexistent@user.com')
    assert r.status_code == 404

    # Delete user
    r = as_root.delete('/users/' + new_user_id)
    assert r.ok


def test_generate_api_key(data_builder, as_public):
    # Try to generate new api key w/o logging in
    r = as_public.post('/users/self/key')
    assert r.status_code == 400

    new_user = data_builder.create_user(api_key='test')
    as_new_user = as_public
    as_new_user.headers.update({'Authorization': 'scitran-user test'})

    # Generate new api key for user
    r = as_new_user.post('/users/self/key')
    assert r.ok
    assert 'key' in r.json()


def test_reset_wechat_registration(data_builder, as_admin):
    new_user = data_builder.create_user()

    # Reset (create) wechat registration code for user
    r = as_admin.post('/users/' + new_user + '/reset-registration')
    assert r.ok
    assert 'registration_code' in r.json()
