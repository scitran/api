import requests
import json
import time
import logging
log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)

base_url = 'http://localhost:8080/api'

def test_groups():
    session = requests.Session()
    # all the requests will be performed as root
    session.params = {
        'user': 'test@user.com',
        'root': True
    }
    _id = 'test_group_' + str(int(time.time()*1000))
    r = session.get(base_url + '/groups/' + _id)
    assert r.status_code == 404
    payload = {
        '_id': _id
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/groups', data=payload)
    assert r.ok
    r = session.get(base_url + '/groups/' + _id)
    assert r.ok
    payload = {
        'name': 'Test group',
    }
    payload = json.dumps(payload)
    r = session.put(base_url + '/groups/' + _id, data=payload)
    assert r.ok
    r = session.delete(base_url + '/groups/' + _id)
    assert r.ok
