import requests
import json
import time
from nose.tools import with_setup
import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)

base_url = 'http://localhost:8080/api'
adm_user = 'test@user.com'
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
    test_data.group_id_1 = 'test_group_' + str(int(time.time()*1000))
    payload = {
        '_id': test_data.group_id_1
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/groups', data=payload)
    assert r.ok

def teardown_db():
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    assert r.ok
    r = session.delete(base_url + '/groups/' + test_data.group_id_1)
    assert r.ok

@with_setup(setup_db, teardown_db)
def test_projects():
    payload = {
        'group': test_data.group_id,
        'label': 'test_project',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    assert r.ok
    _id = json.loads(r.content)['_id']
    r = session.get(base_url + '/projects/' + _id)
    assert r.ok
    payload = {
        'group':  test_data.group_id_1,
    }
    payload = json.dumps(payload)
    r = session.put(base_url + '/projects/' + _id, data=payload)
    assert r.ok
    r = session.delete(base_url + '/projects/' + _id)
    assert r.ok

@with_setup(setup_db, teardown_db)
def test_sessions():
    payload = {
        'group':  test_data.group_id,
        'label': 'test_project',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    assert r.ok
    pid = json.loads(r.content)['_id']
    payload = {
        'project': pid,
        'label': 'session_testing',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/sessions', data=payload)
    assert r.ok
    _id = json.loads(r.content)['_id']
    r = session.get(base_url + '/sessions/' + _id)
    assert r.ok
    payload = {
        'group': test_data.group_id,
        'label': 'test_project_1',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    new_pid = json.loads(r.content)['_id']
    assert r.ok
    payload = {
        'project': new_pid,
    }
    payload = json.dumps(payload)
    r = session.put(base_url + '/sessions/' + _id, data=payload)
    assert r.ok
    r = session.delete(base_url + '/sessions/' + _id)
    assert r.ok
    r = session.get(base_url + '/sessions/' + _id)
    assert r.status_code == 404
    r = session.delete(base_url + '/projects/' + pid)
    assert r.ok
    r = session.delete(base_url + '/projects/' + new_pid)
    assert r.ok

@with_setup(setup_db, teardown_db)
def test_acquisitions():
    payload = {
        'group':  test_data.group_id,
        'label': 'test_project',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    assert r.ok
    pid = json.loads(r.content)['_id']
    payload = {
        'project': pid,
        'label': 'session_testing',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/sessions', data=payload)
    assert r.ok
    sid = json.loads(r.content)['_id']

    payload = {
        'project': pid,
        'label': 'session_testing_1',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/sessions', data=payload)
    assert r.ok
    new_sid = json.loads(r.content)['_id']

    payload = {
        'session': sid,
        'label': 'acq_testing',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/acquisitions', data=payload)
    assert r.ok
    aid = json.loads(r.content)['_id']

    r = session.get(base_url + '/acquisitions/' + aid)
    assert r.ok

    payload = {
        'session': new_sid
    }
    payload = json.dumps(payload)
    r = session.put(base_url + '/acquisitions/' + aid, data=payload)
    assert r.ok

    r = session.delete(base_url + '/acquisitions/' + aid)
    assert r.ok
    r = session.get(base_url + '/acquisitions/' + aid)
    assert r.status_code == 404
    r = session.delete(base_url + '/sessions/' + sid)
    assert r.ok
    r = session.delete(base_url + '/sessions/' + new_sid)
    assert r.ok
    r = session.delete(base_url + '/projects/' + pid)
    assert r.ok
