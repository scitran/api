import requests
import json
import time
import logging
import tarfile
import os
from nose.tools import with_setup

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)
log.setLevel(logging.INFO)


base_url = 'http://localhost:8080/api'
test_data = type('',(object,),{'sessions': [], 'acquisitions': []})()

session = None

file_list = [
    "bids_dataset/CHANGES",
    "bids_dataset/dataset_description.json",
    "bids_dataset/participants.tsv",
    "bids_dataset/README",
    "bids_dataset/task-livingnonlivingdecisionwithplainormirrorreversedtext_bold.json",
    "bids_dataset/sub-01/ses-pre/func/sub-01_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_bold.nii.gz",
    "bids_dataset/sub-01/ses-pre/func/sub-01_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_events.tsv",
    "bids_dataset/sub-01/ses-pre/func/sub-01_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_bold.nii.gz",
    "bids_dataset/sub-01/ses-pre/func/sub-01_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_events.tsv",
    "bids_dataset/sub-01/ses-pre/anat/sub-01_ses-pre_inplaneT2.nii.gz",
    "bids_dataset/sub-01/ses-pre/anat/sub-01_ses-pre_T1w.nii.gz",
    "bids_dataset/sub-01/ses-post/func/sub-01_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_bold.nii.gz",
    "bids_dataset/sub-01/ses-post/func/sub-01_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_events.tsv",
    "bids_dataset/sub-01/ses-post/func/sub-01_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_bold.nii.gz",
    "bids_dataset/sub-01/ses-post/func/sub-01_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_events.tsv",
    "bids_dataset/sub-01/ses-post/anat/sub-01_ses-post_inplaneT2.nii.gz",
    "bids_dataset/sub-01/ses-post/anat/sub-01_ses-post_T1w.nii.gz",
    "bids_dataset/sub-02/ses-pre/func/sub-02_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_bold.nii.gz",
    "bids_dataset/sub-02/ses-pre/func/sub-02_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_events.tsv",
    "bids_dataset/sub-02/ses-pre/func/sub-02_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_bold.nii.gz",
    "bids_dataset/sub-02/ses-pre/func/sub-02_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_events.tsv",
    "bids_dataset/sub-02/ses-pre/anat/sub-02_ses-pre_inplaneT2.nii.gz",
    "bids_dataset/sub-02/ses-pre/anat/sub-02_ses-pre_T1w.nii.gz",
    "bids_dataset/sub-02/ses-post/func/sub-02_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_bold.nii.gz",
    "bids_dataset/sub-02/ses-post/func/sub-02_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_events.tsv",
    "bids_dataset/sub-02/ses-post/func/sub-02_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_bold.nii.gz",
    "bids_dataset/sub-02/ses-post/func/sub-02_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_events.tsv",
    "bids_dataset/sub-02/ses-post/anat/sub-02_ses-post_inplaneT2.nii.gz",
    "bids_dataset/sub-02/ses-post/anat/sub-02_ses-post_T1w.nii.gz",
    "bids_dataset/sub-03/ses-pre/func/sub-03_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_bold.nii.gz",
    "bids_dataset/sub-03/ses-pre/func/sub-03_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_events.tsv",
    "bids_dataset/sub-03/ses-pre/func/sub-03_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_bold.nii.gz",
    "bids_dataset/sub-03/ses-pre/func/sub-03_ses-pre_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_events.tsv",
    "bids_dataset/sub-03/ses-pre/anat/sub-03_ses-pre_inplaneT2.nii.gz",
    "bids_dataset/sub-03/ses-pre/anat/sub-03_ses-pre_T1w.nii.gz",
    "bids_dataset/sub-03/ses-post/func/sub-03_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_bold.nii.gz",
    "bids_dataset/sub-03/ses-post/func/sub-03_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-01_events.tsv",
    "bids_dataset/sub-03/ses-post/func/sub-03_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_bold.nii.gz",
    "bids_dataset/sub-03/ses-post/func/sub-03_ses-post_task-livingnonlivingdecisionwithplainormirrorreversedtext_run-02_events.tsv",
    "bids_dataset/sub-03/ses-post/anat/sub-03_ses-post_inplaneT2.nii.gz",
    "bids_dataset/sub-03/ses-post/anat/sub-03_ses-post_T1w.nii.gz"
]

def file_list_to_tree(file_list):
    # Convert filelist to tree
    dirTree = {}
    for item in file_list:
        path_parts = item.split('/')
        sub_obj = dirTree
        for part in path_parts:
            if not part in sub_obj:
                sub_obj[part] = {} if path_parts.index(part) < len(path_parts) - 1 else 'file'
            sub_obj = sub_obj[part]

    # Convert object lists to arrays
    def objToArr (obj):
        arr = []
        for key in obj:
            if obj[key] == 'file':
                arr.append({'filename': key})
            else:
                arr.append({'name': key, 'children': objToArr(obj[key])})
        return arr

    return objToArr(dirTree)[0]


def setup_download():
    global session
    session = requests.Session()
    # all the requests will be performed as root
    session.params = {
        'user': 'test@user.com',
        'root': True
    }

    # Convert file list to a tree
    dataset = file_list_to_tree(file_list)

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
        'label': dataset['name'],
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    test_data.pid = json.loads(r.content)['_id']
    assert r.ok
    log.debug('pid = \'{}\''.format(test_data.pid))

    # Crawl file tree
    for bidsSubject in dataset['children']:
        if 'filename' in bidsSubject:
            # Upload project files
            files = {'file': (bidsSubject['filename'], 'some,data,to,send'),
                     'tags': ('', '["project"]')}
            r = session.post(base_url + '/projects/' + test_data.pid +'/files', files=files)

        elif 'children' in bidsSubject:
            # Create subject directories
            payload = {
                'project': test_data.pid,
                'label': bidsSubject['name'],
                'subject': {
                    'code': 'subject'
                }
            }
            payload = json.dumps(payload)
            r = session.post(base_url + '/sessions', data=payload)
            subjectId = json.loads(r.content)['_id']
            test_data.sessions.append(subjectId)

            for bidsSession in bidsSubject['children']:
                # Create session directories
                payload = {
                    'project': test_data.pid,
                    'label': bidsSession['name'],
                    'subject': {
                        'code': subjectId
                    }
                }
                payload = json.dumps(payload)
                r = session.post(base_url + '/sessions', data=payload)
                sessionId = json.loads(r.content)['_id']
                test_data.sessions.append(sessionId)

                for bidsModality in bidsSession['children']:
                    # Create modality directories
                    payload = {
                        'session': sessionId,
                        'label': bidsModality['name'],
                    }
                    payload = json.dumps(payload)
                    r = session.post(base_url + '/acquisitions', data=payload)
                    modalityId = json.loads(r.content)['_id']
                    test_data.acquisitions.append(modalityId)

                    for bidsAcquisition in bidsModality['children']:
                        # Upload modality files
                        files = {'file': (bidsAcquisition['filename'], 'some,data,to,send'),
                                 'tags': ('', '["acquisition"]')}
                        r = session.post(base_url + '/acquisitions/' + modalityId +'/files', files=files)


def teardown_download():
    success = True

    # remove all the containers created in the test
    for acquisitionId in test_data.acquisitions:
        r = session.delete(base_url + '/acquisitions/' + acquisitionId)
        success = success and r.ok
    for sessionId in test_data.sessions:
        r = session.delete(base_url + '/sessions/' + sessionId)
        success = success and r.ok
    r = session.delete(base_url + '/projects/' + test_data.pid)
    success = success and r.ok
    r = session.delete(base_url + '/groups/' + test_data.group_id)
    success = success and r.ok
    session.close()

    # remove tar files
    os.remove('test_download.tar')
    os.remove('test_download_symlinks.tar')

    if not success:
        log.error('error in the teardown. These containers may have not been removed.')
        log.error(str(test_data.__dict__))


def download_dataset(symlinks):
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
    r = session.post(base_url + '/download', data=payload, params={'format': 'bids'})
    assert r.ok

    # Perform the download
    ticket = json.loads(r.content)['ticket']
    params = {'ticket': ticket}
    if symlinks:
        params['symlinks'] = True
    r = session.get(base_url + '/download', params=params)
    assert r.ok
    # Save the tar to a file if successful
    f = open('test_download.tar' if not symlinks else 'test_download_symlinks.tar', 'w')
    f.write(r.content)
    f.close()

def get_tar_list(filename):
    # Generate List of files in tar
    tar_list = []
    tar = tarfile.open(filename)
    for member in tar.getmembers():
        tar_list.append(member.path)
    tar.close()
    return tar_list


@with_setup(setup_download, teardown_download)
def test_download():
    download_dataset(False)
    download_dataset(True)

    tar_list = get_tar_list('test_download.tar')
    tar_list_sym = get_tar_list('test_download_symlinks.tar')

    # Sort lists
    file_list.sort()
    tar_list.sort()
    tar_list_sym.sort()

    # Compare tar lists to original
    assert file_list == tar_list
    assert file_list == tar_list_sym

