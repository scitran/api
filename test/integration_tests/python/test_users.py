def test_users(as_root):
    new_user_id = 'new@user.com'

    # List users
    r = as_root.get('/users')
    assert r.ok

    # Get self
    r = as_root.get('/users/self')
    assert r.ok

    # Try adding new user missing required attr
    r = as_root.post('/users', json={
        '_id': 'jane.doe@gmail.com',
        'lastname': 'Doe',
        'email': 'jane.doe@gmail.com',
    })
    assert r.status_code == 400
    assert "'firstname' is a required property" in r.text

    # Add new user
    r = as_root.get('/users/' + new_user_id)
    assert r.status_code == 404
    r = as_root.post('/users', json={
        '_id': new_user_id,
        'firstname': 'New',
        'lastname': 'User',
    })
    assert r.ok
    r = as_root.get('/users/' + new_user_id)
    assert r.ok

    # Modify existing user
    r = as_root.put('/users/' + new_user_id, json={'firstname': 'Realname'})
    assert r.ok

    # Cleanup
    r = as_root.delete('/users/' + new_user_id)
    assert r.ok
