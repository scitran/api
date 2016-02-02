import requests
import json
import time
import logging
from nose.tools import with_setup

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)
log.setLevel(logging.INFO)


base_url = 'http://localhost:8080/api'
test_data = type('',(object,),{})()

session = None

def setup_download():
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

    # Create a project
    payload = {
        'group': test_data.group_id,
        'label': 'scitran_testing',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    test_data.pid = json.loads(r.content)['_id']
    assert r.ok
    log.debug('pid = \'{}\''.format(test_data.pid))

    # Create a session
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

    # Create an acquisition
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

    ## multiform fields for the file upload
    files = {'file': ('test.csv', 'some,data,to,send\nanother,row,to,send\n'),
             'tags': ('', '["incomplete"]'),
             'metadata': ('',
                '{"group": {"_id": "scitran"}, ' \
                '"project": {"label": "Testdata"}, ' \
                '"session": {"uid": "1.2.840.113619.6.353.10437158128305161617400354036593525848"}, ' \
                '"file": {"type": "nifti"}, '
                '"acquisition": {"uid": "1.2.840.113619.2.353.4120.7575399.14591.1403393566.658_1", ' \
                '"timestamp": "1970-01-01T00:00:00", ' \
                '"label": "Screen Save", ' \
                '"instrument": "MRI", ' \
                '"measurement": "screensave", ' \
                '"timezone": "America/Los_Angeles"}, ' \
                '"subject": {"code": "ex7236"}}'
            )}

    # upload the same file to each container created in the test
    session.post(base_url + '/acquisitions/' + test_data.aid +'/files', files=files)
    session.post(base_url + '/sessions/' + test_data.sid +'/files', files=files)
    session.post(base_url + '/projects/' + test_data.pid +'/files', files=files)


def teardown_download():
    success = True
    # remove all the container created in the test
    r = session.delete(base_url + '/acquisitions/' + test_data.aid)
    success = success and r.ok
    r = session.delete(base_url + '/sessions/' + test_data.sid)
    success = success and r.ok
    r = session.delete(base_url + '/projects/' + test_data.pid)
    success = success and r.ok
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    success = success and r.ok
    session.close()
    if not success:
        log.error('error in the teardown. These containers may have not been removed.')
        log.error(str(test_data.__dict__))


@with_setup(setup_download, teardown_download)
def test_download():
    # Retrieve a ticket for a batch download
    payload = {
        'optional': False,
        'nodes': [
            {
                'level': 'project',
                '_id': test_data.pid
            }
        ]
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/download', data=payload)
    assert r.ok

    # Perform the download
    ticket = json.loads(r.content)['ticket']
    r = session.get(base_url + '/download', params={'ticket': ticket})
    assert r.ok
    # Save the tar to a file if successful
    f = open('test_download.tar', 'w')
    f.write(r.content)
    f.close()


