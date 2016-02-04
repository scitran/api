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
test_data = type('',(object,),{})()
base_url = 'http://localhost:8080/api'

def _build_url(_id=None, requestor=adm_user):
    if _id is None:
        url = test_data.proj_url + '?user=' + requestor
    else:
        url = test_data.proj_url + '/' + _id + '?user=' + requestor
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
    test_data.proj_url = base_url + '/projects/{}/notes'.format(test_data.pid)

def teardown_db():
    r = session.delete(base_url + '/projects/' + test_data.pid)
    assert r.ok
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    assert r.ok

@with_setup(setup_db, teardown_db)
def test_notes():
    url_post = test_data.proj_url

    data = {'text':'test note'}
    r = session.post(url_post, data=json.dumps(data))
    assert r.ok
    r = session.get(base_url + '/projects/{}?user={}'.format(test_data.pid, adm_user))
    assert r.ok
    p = json.loads(r.content)
    assert len(p['notes']) == 1
    assert p['notes'][0]['user'] == adm_user
    note_id = p['notes'][0]['_id']
    url_get = test_data.proj_url + '/' + note_id
    r = session.get(url_get)
    assert r.ok
    assert json.loads(r.content)['_id'] == note_id
    data = {'text':'modified test note'}
    r = session.put(url_get, data=json.dumps(data))
    assert r.ok
    r = session.get(url_get)
    assert r.ok
    assert json.loads(r.content)['text'] == 'modified test note'
    r = session.delete(url_get)
    assert r.ok
    r = session.get(url_get)
    assert r.status_code == 404

