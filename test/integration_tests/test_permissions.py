import requests
import json
import time
from nose.tools import with_setup
import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)
log.setLevel(logging.INFO)

adm_user = 'test@user.com'
user = 'other@user.com'
user1 = 'other1@user.com'
test_data = type('',(object,),{})()
base_url = 'http://localhost:8080/api'
session = None

def _build_url(_id=None, requestor=adm_user, site='local'):
    if _id is None:
        url = test_data.proj_url + '?user=' + requestor
    else:
        url = test_data.proj_url + '/' + site + '/' + _id + '?user=' + requestor
    return url


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
        'group': test_data.group_id,
        'label': 'test_project',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    test_data.pid = json.loads(r.content)['_id']
    assert r.ok
    log.debug('pid = \'{}\''.format(test_data.pid))
    test_data.proj_url = base_url + '/projects/{}/permissions'.format(test_data.pid)

def teardown_db():
    r = session.delete(base_url + '/projects/' + test_data.pid)
    assert r.ok
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    assert r.ok

@with_setup(setup_db, teardown_db)
def test_permissions():
    url_post = _build_url()
    url_get = _build_url(user)
    url_get_1 = _build_url(user1)
    r = requests.get(url_get)
    assert r.status_code == 404
    data = {
        '_id': user,
        'site': 'local',
        'access': 'ro'
    }
    r = requests.post(url_post, data = json.dumps(data))
    assert r.ok
    r = requests.get(url_get)
    assert r.ok
    content = json.loads(r.content)
    assert content['_id'] == user
    assert content['site'] == 'local'
    assert content['access'] == 'ro'
    data = {
        'access': 'admin'
    }
    r = requests.put(url_get, data = json.dumps(data))
    assert r.ok
    data = {
        '_id': user1,
        'site': 'local',
        'access': 'ro'
    }
    r = requests.post(url_post, data = json.dumps(data))
    assert r.ok
    data = {
        '_id': user
    }
    r = requests.put(url_get_1, data = json.dumps(data))
    assert r.status_code == 404
    data = {
        'site': 'another'
    }
    r = requests.put(url_get_1, data = json.dumps(data))
    assert r.ok
    url_get_1 = _build_url(user1, site='another')
    r = requests.get(url_get_1)
    assert r.ok
    content = json.loads(r.content)
    assert content['_id'] == user1
    assert content['site'] == 'another'
    assert content['access'] == 'ro'
    r = requests.delete(url_get_1)
    assert r.ok
    r = requests.get(url_get_1)
    assert r.status_code == 404
