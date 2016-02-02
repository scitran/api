import requests
import json
import time
from nose.tools import with_setup
import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)
log.setLevel(logging.INFO)

adm_user = 'admin@user.com'
test_data = type('',(object,),{})()
base_url = 'http://localhost:8080/api'
session = None

def _build_url_and_payload(method, tag, newtag=None, requestor=adm_user):
    if method == 'POST':
        url = test_data.proj_url
        payload = json.dumps({'value': tag})
    else:
        url = test_data.proj_url + '/' + tag
        payload = json.dumps({'value': newtag})
    return url, payload

def setup_db():
    global session
    session = requests.Session()
    # all the requests will be performed as root
    session.params = {
        'user': 'test@user.com',
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
    test_data.proj_url = base_url + '/projects/{}/tags'.format(test_data.pid)

def teardown_db():
    r = session.delete(base_url + '/projects/' + test_data.pid)
    assert r.ok
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    assert r.ok

@with_setup(setup_db, teardown_db)
def test_tags():
    tag = 'test_tag'
    new_tag = 'new_test_tag'
    other_tag = 'other_test_tag'
    url_get_tag, _ = _build_url_and_payload('GET', tag)
    url_get_new, _ = _build_url_and_payload('GET', new_tag)
    url_get_other, _ = _build_url_and_payload('GET', other_tag)

    r = session.get(url_get_tag)
    assert r.status_code == 404
    url_post, payload = _build_url_and_payload('POST', tag)
    r = session.post(url_post, data=payload)
    assert r.ok
    r = session.get(url_get_tag)
    assert r.ok
    assert json.loads(r.content) == tag

    url_post, payload = _build_url_and_payload('POST', new_tag)
    r = session.post(url_post, data=payload)
    assert r.ok
    url_post, payload = _build_url_and_payload('POST', new_tag)
    r = session.post(url_post, data=payload)
    assert r.status_code == 404
    r = session.get(url_get_new)
    assert r.ok
    assert json.loads(r.content) == new_tag

    url_put, payload = _build_url_and_payload('PUT', tag, new_tag)
    r = session.put(url_put, data=payload)
    assert r.status_code == 404

    r = session.get(url_get_other, verify=False)
    assert r.status_code == 404
    url_put, payload = _build_url_and_payload('PUT', tag, other_tag)
    r = session.put(url_put, data=payload)
    assert r.ok
    r = session.get(url_get_other)
    assert r.ok
    assert json.loads(r.content) == other_tag

    r = session.get(url_get_tag)
    assert r.status_code == 404
    r = session.delete(url_get_other) # url for 'DELETE' is the same as the one for 'GET'
    assert r.ok
    r = session.get(url_get_other)
    assert r.status_code == 404
    r = session.delete(url_get_new) # url for 'DELETE' is the same as the one for 'GET'
    assert r.ok
    r = session.get(url_get_new)
    assert r.status_code == 404
