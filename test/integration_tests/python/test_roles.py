import datetime
import json
import time

import pytest


@pytest.fixture()
def with_a_group_and_a_user(data_builder, api_as_admin, request, bunch):
    user_id = 'other@user.com'
    group_id = 'test_group_' + str(int(time.time() * 1000))
    data_builder.create_group(group_id)

    payload = json.dumps({
        '_id': user_id,
        'firstname': 'Other',
        'lastname': 'User',
    })
    r = api_as_admin.post('/users', data=payload)
    assert r.ok

    def teardown_db():
        data_builder.delete_group(group_id)
        api_as_admin.delete('/users/' + user_id)

    request.addfinalizer(teardown_db)

    fixture_data = bunch.create()
    fixture_data.user_id = user_id
    fixture_data.group_id = group_id
    return fixture_data


def create_role_payload(user, site, access):
    return json.dumps({
        '_id': user,
        'site': site,
        'access': access
    })


def test_roles(api_as_admin, with_a_group_and_a_user, api_accessor, db):
    data = with_a_group_and_a_user
    user_api_key = "4hOn5aBx/nUiI0blDbTUPpKQsEbEn74rH9z5KctlXw6GrMKdicPGXKQg"
    api_key_doc = {
        "key":user_api_key,
        "created":datetime.datetime.utcnow()
    }
    update_result = db.users.update_one(
        {"_id":data.user_id},
        {"$set":{"api_key":api_key_doc}}
        )
    assert update_result.modified_count == 1
    api_as_other_user = api_accessor(user_api_key)

    roles_path = '/groups/' + data.group_id + '/roles'
    local_user_roles_path = roles_path + '/local/' + data.user_id
    admin_user_roles_path = roles_path + '/local/' + 'admin@user.com'

    # Cannot retrieve roles that don't exist
    r = api_as_admin.get(local_user_roles_path)
    assert r.status_code == 404

    # Create role for user
    payload = create_role_payload(data.user_id, 'local', 'rw')
    r = api_as_admin.post(roles_path, data=payload)
    assert r.ok

    # Verify new user role
    r = api_as_admin.get(local_user_roles_path)
    assert r.ok
    content = json.loads(r.content)
    assert content['access'] == 'rw'
    assert content['_id'] == data.user_id

    # 'rw' users cannot access other user roles
    r = api_as_other_user.get(admin_user_roles_path)
    assert r.status_code == 403

    # Upgrade user to admin
    payload = json.dumps({'access': 'admin'})
    r = api_as_admin.put(local_user_roles_path, data=payload)
    assert r.ok

    # User should now be able to access other roles
    r = api_as_other_user.get(admin_user_roles_path)
    assert r.ok

    # Change user back to 'rw' access
    payload = json.dumps({'access': 'rw'})
    r = api_as_admin.put(local_user_roles_path, data=payload)
    assert r.ok

    # User is now forbidden again
    r = api_as_other_user.get(admin_user_roles_path)
    assert r.status_code == 403

    # Delete role
    r = api_as_admin.delete(local_user_roles_path)
    assert r.ok

    # Verify delete
    r = api_as_admin.get(local_user_roles_path)
    assert r.status_code == 404
