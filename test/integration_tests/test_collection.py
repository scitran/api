import requests
import json
import time
import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)
log.setLevel(logging.INFO)

from nose.tools import with_setup
import pymongo
from bson.objectid import ObjectId

db = pymongo.MongoClient('mongodb://localhost:9001/scitran').get_default_database()
adm_user = 'test@user.com'
base_url = 'http://localhost:8080/api'
test_data = type('',(object,),{})()

def setup_db():
    global session
    session = requests.Session()
    session.params = {
        'user': adm_user,
        'root': True
    }
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

    payload = {
        'project': test_data.pid,
        'label': 'session_testing',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/sessions', data=payload)
    assert r.ok
    test_data.sid = json.loads(r.content)['_id']
    log.debug('sid = \'{}\''.format(test_data.sid))

    payload = {
        'session': test_data.sid,
        'label': 'acq_testing',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/acquisitions', data=payload)
    assert r.ok
    test_data.aid = json.loads(r.content)['_id']
    log.debug('aid = \'{}\''.format(test_data.aid))

def teardown_db():
    session.params['root'] = True
    r = session.delete(base_url + '/acquisitions/' + test_data.aid)
    assert r.ok
    r = session.delete(base_url + '/sessions/' + test_data.sid)
    assert r.ok
    r = session.delete(base_url + '/projects/' + test_data.pid)
    assert r.ok


@with_setup(setup_db, teardown_db)
def test_collections():
    payload = {
        'curator': adm_user,
        'label': 'test_collection_'+ str(int(time.time())) ,
        'public': False
    }
    session.params['root'] = False
    r = session.post(base_url + '/collections', data=json.dumps(payload))
    assert r.ok
    _id = json.loads(r.content)['_id']
    log.debug('_id = \'{}\''.format(_id))
    r = session.get(base_url + '/collections/' + _id)
    assert r.ok
    payload = {
        'contents':{
            'nodes':
            [{
                'level': 'session',
                '_id': test_data.sid
            }],
            'operation': 'add'
        }
    }
    r = session.put(base_url + '/collections/' + _id, data=json.dumps(payload))
    assert r.ok
    r = session.get(base_url + '/collections/' + _id + '/acquisitions?session=' + test_data.sid)
    assert r.ok
    coll_acq_id= json.loads(r.content)[0]['_id']
    assert coll_acq_id  == test_data.aid
    acq_ids = [ObjectId(test_data.aid)]
    acs = db.acquisitions.find({'_id': {'$in': acq_ids}})
    for ac in acs:
        assert len(ac['collections']) == 1
        assert ac['collections'][0] == ObjectId(_id)
    r = session.delete(base_url + '/collections/' + _id)
    assert r.ok
    r = session.get(base_url + '/collections/' + _id)
    assert r.status_code == 404
    acs = db.acquisitions.find({'_id': {'$in': acq_ids}})
    for ac in acs:
        assert len(ac['collections']) == 0
