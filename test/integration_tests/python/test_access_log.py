import time

from api.web.request import AccessType


# NOTE these tests assume they are not running in parallel w/ other tests
# by relying on the last entry in the logs

def test_access_log_succeeds(data_builder, as_admin, log_db):
    project = data_builder.create_project()
    session = data_builder.create_session()
    file_name = 'one.csv'

    ###
    # Test login action is logged
    ###

    api_key = as_admin.get('/users/self').json()['api_key']['key']

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.post('/login', json={
        'auth_type': 'api-key',
        'code': api_key
    })
    assert r.ok

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]
    assert most_recent_log['access_type'] == AccessType.user_login.value


    ###
    # Test logout action is logged
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.post('/logout')
    assert r.ok

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]
    assert most_recent_log['access_type'] == AccessType.user_logout.value


    ###
    # Test session access is logged
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.get('/sessions/' + session)
    assert r.ok

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]

    assert most_recent_log['context']['session']['id'] == str(session)
    assert most_recent_log['access_type'] == AccessType.view_container.value


    ###
    # Add subject info
    ###

    subject_code = 'Test subject code'
    r = as_admin.put('/sessions/' + session, json={
        'subject': {'code': subject_code}}
    )
    assert r.ok


    ###
    # Test subject access is logged
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.get('/sessions/' + session + '/subject')
    assert r.ok

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]

    assert most_recent_log['context']['session']['id'] == session
    assert most_recent_log['context']['subject']['label'] == subject_code
    assert most_recent_log['access_type'] == AccessType.view_subject.value


    # Upload files
    r = as_admin.post('/projects/' + project + '/files', files={
        'file': (file_name, 'test-content')
    })
    assert r.ok


    ###
    # Test file download is logged
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.get('/projects/' + project + '/files/' + file_name)
    assert r.ok

    file_ = r.raw.read(10)
    time.sleep(1)

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]

    assert most_recent_log['context']['project']['id'] == project
    assert most_recent_log['access_type'] == AccessType.download_file.value


    ###
    # Test file ticket download is logged once
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.get('/projects/' + project + '/files/' + file_name, params={'ticket': ''})
    assert r.ok

    ticket_id = r.json()['ticket']

    r = as_admin.get('/projects/' + project + '/files/' + file_name, params={'ticket': ticket_id})
    assert r.ok

    file_ = r.raw.read(10)
    time.sleep(1)

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]

    assert most_recent_log['context']['project']['id'] == str(project)
    assert most_recent_log['context']['ticket_id'] == ticket_id
    assert most_recent_log['access_type'] == AccessType.download_file.value


    ###
    # Test file info access is logged
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.get('/projects/' + project + '/files/' + file_name + '/info')
    assert r.ok
    assert r.json()['name'] == file_name

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]

    assert most_recent_log['context']['project']['id'] == str(project)
    assert most_recent_log['access_type'] == AccessType.view_file.value


    ###
    # Test file delete is logged
    ###

    log_records_count_before = log_db.access_log.count({})

    r = as_admin.delete('/projects/' + project + '/files/' + file_name)
    assert r.ok

    log_records_count_after = log_db.access_log.count({})
    assert log_records_count_before+1 == log_records_count_after

    most_recent_log = log_db.access_log.find({}).sort([('_id', -1)]).limit(1)[0]

    assert most_recent_log['context']['project']['id'] == str(project)
    assert most_recent_log['access_type'] == AccessType.delete_file.value


def test_access_log_fails(data_builder, as_admin, log_db):
    project = data_builder.create_project()
    file_name = 'one.csv'

    log_db.command('collMod', 'access_log', validator={'$and': [{'foo': {'$exists': True}}]}, validationLevel='strict')

    # Upload files
    r = as_admin.post('/projects/' + project + '/files', files={
        'file': (file_name, 'test-content')
    })
    assert r.ok

    ###
    # Test file delete request fails and does not delete file
    ###

    r = as_admin.delete('/projects/' + project + '/files/' + file_name)
    assert r.status_code == 500

    r = as_admin.get('/projects/' + project)
    assert r.ok
    assert r.json()['files']

    log_db.command('collMod', 'access_log', validator={}, validationLevel='strict')
