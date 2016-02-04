import requests
import os
import json
import time
from nose.tools import with_setup

base_url = 'http://localhost:8080/api'
adm_user = 'test@user.com'
user = 'other@user.com'
test_data = type('',(object,),{})()


def setup_db():
    global session
    session = requests.Session()
    # all the requests will be performed as root
    session.params = {
        'user': adm_user,
        'root': True
    }

    # Create a group
    test_data.group_id = 'test_group_' + str(int(time.time()*1000))
    payload = {
        '_id': test_data.group_id
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/groups', data=payload)
    assert r.ok
    payload = {
        '_id': user,
        'firstname': 'Other',
        'lastname': 'User',
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/users', data=payload)
    assert r.ok
    session.params = {}

def teardown_db():
    session.params = {
        'user': adm_user,
        'root': True
    }
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    assert r.ok
    r = session.delete(base_url + '/users/' + user)
    assert r.ok

def _build_url_and_payload(method, user, access, site='local'):

    url = os.path.join(base_url, 'groups', test_data.group_id, 'roles')
    if method == 'POST':
        payload = {
            '_id': user,
            'site': site,
            'access': access
        }
        return url, json.dumps(payload)
    else:
        return os.path.join(url, site, user), None

@with_setup(setup_db, teardown_db)
def test_roles():
    session.params = {
        'user': adm_user
    }
    url_get, _ = _build_url_and_payload('GET', user, None)
    r = session.get(url_get)
    assert r.status_code == 404

    url_post, payload = _build_url_and_payload('POST', user, 'rw')
    r = session.post(url_post, data=payload)
    assert r.ok
    r = session.get(url_get)
    assert r.ok
    content = json.loads(r.content)
    assert content['access'] == 'rw'
    assert content['_id'] == user
    session.params = {
        'user': user
    }
    url_get_not_auth, _ = _build_url_and_payload('GET', adm_user, None)
    r = session.get(url_get_not_auth)
    assert r.status_code == 403
    session.params = {
        'user': adm_user
    }
    payload = json.dumps({'access':'admin'})
    r = session.put(url_get, data=payload)
    assert r.ok
    session.params = {
        'user': user
    }
    r = session.get(url_get_not_auth)
    assert r.ok
    session.params = {
        'user': adm_user
    }
    payload = json.dumps({'access':'rw'})
    r = session.put(url_get, data=payload)
    assert r.ok
    session.params = {
        'user': user
    }
    r = session.get(url_get_not_auth)
    assert r.status_code == 403
    session.params = {
        'user': adm_user
    }
    r = session.delete(url_get)
    assert r.ok
    r = session.get(url_get)
    assert r.status_code == 404
