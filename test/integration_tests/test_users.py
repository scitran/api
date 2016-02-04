import requests
import json
import logging
log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)

requests.packages.urllib3.disable_warnings()

base_url = 'http://localhost:8080/api'

def test_users():
    _id = 'new@user.com'
    r = requests.get(base_url + '/users/self?user=test@user.com')
    assert r.ok
    r = requests.get(base_url + '/users/' + _id + '?user=test@user.com&root=true')
    assert r.status_code == 404
    payload = {
        '_id': _id,
        'firstname': 'New',
        'lastname': 'User',
    }
    payload = json.dumps(payload)
    r = requests.post(base_url + '/users?user=test@user.com&root=true', data=payload)
    assert r.ok
    r = requests.get(base_url + '/users/' + _id + '?user=test@user.com&root=true')
    assert r.ok
    payload = {
        'firstname': 'Realname'
    }
    payload = json.dumps(payload)
    r = requests.put(base_url + '/users/' + _id + '?user=test@user.com&root=true', data=payload)
    assert r.ok
    r = requests.delete(base_url + '/users/' + _id + '?user=test@user.com&root=true')
    assert r.ok
