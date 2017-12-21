# Test changing propagated properties
def test_archived_propagation_from_project(data_builder, as_admin):
    """
    Tests:
      - 'archived' is a propagated property
      - propagation works from a project level
      - setting a propagated property triggers propagation
      - set logic for setting 1 of the propagated properties
    """
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    payload = {'archived': True}
    r = as_admin.put('/projects/' + project, json=payload)
    assert r.ok

    r = as_admin.get('/projects/' + project)
    assert r.ok and r.json()['archived']

    r = as_admin.get('/sessions/' + session)
    assert r.ok and r.json()['archived']

    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok and r.json()['archived']


def test_public_propagation_from_project(data_builder, as_admin):
    """
    Tests:
      - 'public' is a propagated property
    """
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    payload = {'public': False}
    r = as_admin.put('/projects/' + project, json=payload)
    assert r.ok

    r = as_admin.get('/projects/' + project)
    assert r.ok and not r.json()['public']

    r = as_admin.get('/sessions/' + session)
    assert r.ok and not r.json()['public']

    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok and not r.json()['public']


def test_public_and_archived_propagation_from_project(data_builder, as_admin):
    """
    Tests:
      - set logic for setting all of the propagated properties
    """
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    payload = {'public': False, 'archived': False}
    r = as_admin.put('/projects/' + project, json=payload)
    assert r.ok

    r = as_admin.get('/projects/' + project)
    content = r.json()
    assert r.ok and not content['public'] and not content['archived']

    r = as_admin.get('/sessions/' + session)
    content = r.json()
    assert r.ok and not content['public'] and not content['archived']

    r = as_admin.get('/acquisitions/' + acquisition)
    content = r.json()
    assert r.ok and not content['public'] and not content['archived']


def test_public_propagation_from_session(data_builder, as_admin):
    """
    Tests:
      - propagation works from a session level
    """
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    payload = {'archived': True}
    r = as_admin.put('/sessions/' + session, json=payload)
    assert r.ok

    r = as_admin.get('/sessions/' + session)
    assert r.ok and r.json()['archived']

    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok and r.json()['archived']


def test_set_public_acquisition(data_builder, as_admin):
    """
    Tests:
      - setting a propagated property on an acquisition does not attempt to propagate (would hit Exception)
    """
    acquisition = data_builder.create_acquisition()

    payload = {'archived': True}
    r = as_admin.put('/acquisitions/' + acquisition, json=payload)
    assert r.ok


# Test propagation of project permission changes
def test_add_and_remove_user_for_project_permissions(data_builder, as_admin):
    """
    Tests:
      - changing permissions at a project level triggers propagation
      - additive change to list propagates properly
      - change to list propagates properly
      - removal from list propagates properly
    """
    def get_user_in_perms(perms, uid):
        for perm in perms:
            if perm['_id'] == uid:
                return perm
        return None

    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    user_id = 'propagation@user.com'

    # Add user to project permissions
    payload = {'_id': user_id, 'access': 'admin', 'phi-access': True}
    r = as_admin.post('/projects/' + project + '/permissions', json=payload)
    assert r.ok

    r = as_admin.get('/projects/' + project)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user

    r = as_admin.get('/sessions/' + session)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user

    r = as_admin.get('/acquisitions/' + acquisition)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user

    # Modify user permissions
    payload = {'access': 'rw', '_id': user_id, 'phi-access': True}
    r = as_admin.put('/projects/' + project + '/permissions/' + user_id, json=payload)
    assert r.ok

    r = as_admin.get('/projects/' + project)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    r = as_admin.get('/sessions/' + session)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    r = as_admin.get('/acquisitions/' + acquisition)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    # Remove user from project permissions
    r = as_admin.delete('/projects/' + project + '/permissions/' + user_id, json=payload)
    assert r.ok

    r = as_admin.get('/projects/' + project)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

    r = as_admin.get('/sessions/' + session)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

    r = as_admin.get('/acquisitions/' + acquisition)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

# Test group permission propagation
def test_add_and_remove_user_group_permission(data_builder, as_admin):
    """
    Tests:
      - changing permissions at a group level with flag triggers propagation
      - additive change to list propagates properly
      - change to list propagates properly
      - removal from list propagates properly
    """
    def get_user_in_perms(perms, uid):
        for perm in perms:
            if perm['_id'] == uid:
                return perm
        return None

    group = data_builder.create_group()
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    user_id = 'propagation@user.com'

    # Add user to group permissions
    payload = {'_id': user_id, 'access': 'admin', 'phi-access': True}
    r = as_admin.post('/groups/' + group + '/permissions', json=payload, params={'propagate': 'true'})
    assert r.ok

    # Add project without default group perms
    r = as_admin.post('/projects', params={'inherit': 'false'}, json={'label': 'project2', 'group': group, 'phi' : True})
    assert r.ok
    project2 = r.json()['_id']


    r = as_admin.get('/groups/' + group)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user

    r = as_admin.get('/projects/' + project)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.json()['group'] == group
    assert r.ok and user

    r = as_admin.get('/sessions/' + session)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user

    r = as_admin.get('/acquisitions/' + acquisition)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user

    # Modify user permissions
    payload = {'access': 'rw', '_id': user_id, 'phi-access':True}
    r = as_admin.put('/groups/' + group + '/permissions/' + user_id, json=payload, params={'propagate': 'true'})
    assert r.ok

    r = as_admin.get('/groups/' + group)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    r = as_admin.get('/projects/' + project)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    r = as_admin.get('/projects/' + project2)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    r = as_admin.get('/sessions/' + session)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    r = as_admin.get('/acquisitions/' + acquisition)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user and user['access'] == 'rw'

    # Remove user from project permissions
    r = as_admin.delete('/groups/' + group + '/permissions/' + user_id, json=payload, params={'propagate': 'true'})
    assert r.ok

    r = as_admin.get('/groups/' + group)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

    r = as_admin.get('/projects/' + project)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

    r = as_admin.get('/sessions/' + session)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

    r = as_admin.get('/acquisitions/' + acquisition)
    perms = r.json()['permissions']
    user = get_user_in_perms(perms, user_id)
    assert r.ok and user is None

    # Delete empty project 2
    r= as_admin.delete('/projects/' + project2)
    assert r.ok

# Test tag pool renaming and deletion
def test_add_rename_remove_group_tag(data_builder, as_admin):
    """
    Tests:
      - propagation from the group level
      - renaming tag at group level renames tags in hierarchy
      - deleting tag at group level renames tags in hierarchy
    """

    group = data_builder.create_group()
    project = data_builder.create_project()
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()

    tag = 'test tag'
    tag_renamed = 'test tag please ignore'


    # Add tag to hierarchy
    payload = {'value': tag}
    r = as_admin.post('/groups/' + group + '/tags', json=payload)
    assert r.ok
    r = as_admin.post('/projects/' + project + '/tags', json=payload)
    assert r.ok
    r = as_admin.post('/sessions/' + session + '/tags', json=payload)
    assert r.ok
    r = as_admin.post('/acquisitions/' + acquisition + '/tags', json=payload)
    assert r.ok

    r = as_admin.get('/groups/' + group)
    assert r.ok and tag in r.json()['tags']
    r = as_admin.get('/projects/' + project)
    assert r.ok and tag in r.json()['tags']
    r = as_admin.get('/sessions/' + session)
    assert r.ok and tag in r.json()['tags']
    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok and tag in r.json()['tags']

    # Rename tag
    payload = {'value': tag_renamed}
    r = as_admin.put('/groups/' + group + '/tags/' + tag, json=payload)
    assert r.ok

    r = as_admin.get('/groups/' + group)
    assert r.ok and tag_renamed in r.json()['tags']
    r = as_admin.get('/projects/' + project)
    assert r.ok and tag_renamed in r.json()['tags']
    r = as_admin.get('/sessions/' + session)
    assert r.ok and tag_renamed in r.json()['tags']
    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok and tag_renamed in r.json()['tags']

    # Delete tag
    r = as_admin.delete('/groups/' + group + '/tags/' + tag_renamed)
    assert r.ok

    r = as_admin.get('/groups/' + group)
    assert r.ok and tag_renamed not in r.json()['tags']
    r = as_admin.get('/projects/' + project)
    assert r.ok and tag_renamed not in r.json()['tags']
    r = as_admin.get('/sessions/' + session)
    assert r.ok and tag_renamed not in r.json()['tags']
    r = as_admin.get('/acquisitions/' + acquisition)
    assert r.ok and tag_renamed not in r.json()['tags']
