import requests
import json
import logging
log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)
import warnings
warnings.filterwarnings('ignore')
base_url = 'http://localhost:8080/api'

import pymongo
db = pymongo.MongoClient('mongodb://localhost:9001/scitran').get_default_database()
projects = db.projects

def test_extra_param():
    payload = {
        'group': 'unknown',
        'label': 'SciTran/Testing',
        'public': False,
        'extra_param': 'some_value'
    }
    payload = json.dumps(payload)
    r = requests.post(base_url + '/projects?user=test@user.com&root=true', data=payload)
    assert r.status_code == 400
    r = projects.delete_many({'label': 'SciTran/Testing'})
    assert r.deleted_count == 0
