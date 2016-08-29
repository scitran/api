import json
import time
import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)


def test_extra_param(api_as_admin):
    label = 'SciTran/testing_' + str(int(time.time() * 1000))

    bad_payload = json.dumps({
        'group': 'unknown',
        'label': label,
        'public': False,
        'extra_param': 'some_value'
    })

    r = api_as_admin.post('/projects', data=bad_payload)
    assert r.status_code == 422

    r = api_as_admin.get('/projects')
    assert r.ok
    projects = json.loads(r.content)
    filtered_projects = filter(lambda e: e['label'] == label, projects)
    assert len(filtered_projects) == 0
