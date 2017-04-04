def test_gear_add(default_payload, randstr, as_root):
    gear_name = 'test-gear-add-' + randstr()
    gear_payload = default_payload['gear']
    gear_payload['gear']['name'] = gear_name

    # create new gear
    r = as_root.post('/gears/' + gear_name, json=gear_payload)
    assert r.ok
    _id = r.json()['_id']

    # get gear by id, test name
    r = as_root.get('/gears/' + _id)
    assert r.ok
    assert r.json()['gear']['name'] == gear_name

    # try to get gear by name
    r = as_root.get('/gears/' + gear_name)
    assert not r.ok

    # delete gear
    r = as_root.delete('/gears/' + _id)
    assert r.ok


def test_gear_add_versioning(default_payload, randstr, as_root):
    gear_name = 'test-gear-add-versioning-' + randstr()
    gear_version_1 = '0.0.1'
    gear_version_2 = '0.0.2'

    gear_payload = default_payload['gear']
    gear_payload['gear']['name'] = gear_name

    # create new gear w/ gear_version_1
    gear_payload['gear']['version'] = gear_version_1
    r = as_root.post('/gears/' + gear_name, json=gear_payload)
    assert r.ok
    gear_id_1 = r.json()['_id']

    # get gear by id, test name and version
    r = as_root.get('/gears/' + gear_id_1)
    assert r.ok
    assert r.json()['gear']['name'] == gear_name
    assert r.json()['gear']['version'] == gear_version_1

    # list gears, test gear name occurs only once
    r = as_root.get('/gears', params={'fields': 'all'})
    assert r.ok
    assert sum(gear['gear']['name'] == gear_name for gear in r.json()) == 1

    # create new gear w/ gear_version_2
    gear_payload['gear']['version'] = gear_version_2
    r = as_root.post('/gears/' + gear_name, json=gear_payload)
    assert r.ok
    gear_id_2 = r.json()['_id']

    # get gear by id, test name and version
    r = as_root.get('/gears/' + gear_id_2)
    assert r.ok
    assert r.json()['gear']['name'] == gear_name
    assert r.json()['gear']['version'] == gear_version_2

    # list gears, test gear name occurs only once
    r = as_root.get('/gears', params={'fields': 'all'})
    assert r.ok
    assert sum(gear['gear']['name'] == gear_name for gear in r.json()) == 1

    # try to create gear w/ same name and version (gear_version_2)
    r = as_root.post('/gears/' + gear_name, json=gear_payload)
    assert not r.ok


def test_gear_add_invalid(default_payload, randstr, as_root):
    gear_name = 'test-gear-add-invalid-' + randstr()

    # try to add invalid gear - missing name
    r = as_root.post('/gears/' + gear_name, json={})
    assert r.status_code == 400

    # try to add invalid gear - manifest validation error
    r = as_root.post('/gears/' + gear_name, json={'gear': {'name': gear_name}})
    assert r.status_code == 400

    # try to add invalid gear - manifest validation error of non-root-level key
    gear_payload = default_payload['gear']
    gear_payload['gear']['inputs'] = {'invalid': 'inputs'}
    r = as_root.post('/gears/' + gear_name, json=gear_payload)
    assert r.status_code == 400


def test_gear_access(data_builder, as_public, as_admin):
    gear = data_builder.create_gear()

    # test login required
    r = as_public.get('/gears')
    assert r.status_code == 403

    r = as_public.get('/gears/' + gear)
    assert r.status_code == 403

    r = as_public.get('/gears/' + gear + '/invocation')
    assert r.status_code == 403

    r = as_public.get('/gears/' + gear + '/suggest/test-container/test-id')
    assert r.status_code == 403

    # test superuser required
    r = as_admin.post('/gears/' + gear, json={'test': 'payload'})
    assert r.status_code == 403

    r = as_admin.delete('/gears/' + gear)
    assert r.status_code == 403


def test_gear_invocation_and_suggest(data_builder, as_user, as_admin):
    gear = data_builder.create_gear()
    session = data_builder.create_session()

    # test invocation
    r = as_admin.get('/gears/' + gear + '/invocation')
    assert r.ok

    # test suggest
    r = as_admin.get('/gears/' + gear + '/suggest/session/' + session)
    assert r.ok
