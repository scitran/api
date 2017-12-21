import calendar
import copy
import datetime
from api.web.request import AccessTypeList

# create timestamps for report filtering
today = datetime.datetime.today()
ts_format = '{:%Y-%m-%dT%H:%M:%S+00:00}'
yesterday_ts = ts_format.format(today - datetime.timedelta(days=1))
tomorrow_ts = ts_format.format(today + datetime.timedelta(days=1))


def test_site_report(data_builder, randstr, as_admin, as_user):
    group_label = randstr()
    group = data_builder.create_group(label=group_label)
    project = data_builder.create_project()
    session = data_builder.create_session()

    # try to get site report as non-admin
    r = as_user.get('/report/site')
    assert r.status_code == 403

    # get site report
    r = as_admin.get('/report/site')
    assert r.ok

    site_report = r.json()
    group_report = next((g for g in site_report['groups'] if g['label'] == group_label), None)
    assert group_report is not None
    assert group_report['project_count'] == 1
    assert group_report['session_count'] == 1


def test_project_report(data_builder, as_admin, as_user):
    project_1 = data_builder.create_project()
    project_2 = data_builder.create_project()

    seconds_per_year = int(365.25 * 24 * 60 * 60)
    session_1 = data_builder.create_session(project=project_1)
    session_2 = data_builder.create_session(
        project=project_1,
        subject={'sex': 'male', 'age': 17*seconds_per_year}
    )
    session_3 = data_builder.create_session(
        project=project_1,
        subject={'sex': 'female', 'age': 19*seconds_per_year, 'race': 'Asian'}
    )

    # try to get project report w/o perms
    r = as_user.get('/report/project', params={'projects': [project_1, project_2]})
    assert r.status_code == 403

    # try to get project report w/o 'projects' param
    r = as_admin.get('/report/project')
    assert r.status_code == 400

    # try to use an invalid date filter (end < start)
    r = as_admin.get('/report/project', params={
        'projects': project_1,
        'start_date': tomorrow_ts,
        'end_date': yesterday_ts,
    })
    assert r.status_code == 400

    # get project report w/ date filter not matching sessions
    r = as_admin.get('/report/project', params={
        'projects': project_1,
        'end_date': yesterday_ts,
    })
    assert r.ok
    projects = r.json()['projects']
    assert len(projects) == 1
    assert projects[0]['session_count'] == 0

    # get project report w/ date filter matching sessions
    r = as_admin.get('/report/project', params={
        'projects': project_1,
        'start_date': yesterday_ts,
        'end_date': tomorrow_ts,
    })
    assert r.ok
    projects = r.json()['projects']
    assert len(projects) == 1
    assert projects[0]['session_count'] == 3
    assert projects[0]['male_count'] == projects[0]['female_count'] == 1
    assert projects[0]['under_18_count'] == projects[0]['over_18_count'] == 1

    # get project report for multiple projects
    # test empty project (no sessions) handling w/ project_2
    r = as_admin.get('/report/project', params={'projects': [project_1, project_2]})
    assert r.ok
    project_report = r.json()
    assert len(project_report['projects']) == 2


def test_access_log_report(data_builder, with_user, as_user, as_admin):
    # try to get access log report as user
    r = as_user.get('/report/accesslog')
    assert r.status_code == 403

    # try to get access log report w/ invalid date filter (end < start)
    r = as_admin.get('/report/accesslog', params={
        'start_date': tomorrow_ts, 'end_date': yesterday_ts
    })
    assert r.status_code == 400

    # try to get access log report w/ invalid uid (space)
    r = as_admin.get('/report/accesslog', params={'user': 'uid wannabe'})
    assert r.status_code == 400

    # try to get access log report w/ non-int limit
    r = as_admin.get('/report/accesslog', params={'limit': 'int wannabe'})
    assert r.status_code == 400

    # try to get access log report w/ limit < 1
    r = as_admin.get('/report/accesslog', params={'limit': 0})
    assert r.status_code == 400

    # try to get report w/ limit == 1000 and limit > 1000
    r = as_admin.get('/report/accesslog', params={'limit': 10000})
    assert r.ok
    r = as_admin.get('/report/accesslog', params={'limit': 10001})
    assert r.status_code == 400

    # get access log report for user
    r = as_admin.get('/report/accesslog', params={
        'start_date': yesterday_ts, 'end_date': tomorrow_ts, 'user': with_user.user
    })
    assert r.ok
    assert r.json() == []

    # get access log report for user
    with_user.session.post('/login', json={'auth_type': 'api-key', 'code': with_user.api_key})
    r = as_admin.get('/report/accesslog', params={
        'user': with_user.user,
        'start_date': yesterday_ts,
        'end_date': tomorrow_ts,
    })
    assert r.ok
    accesslog = r.json()
    assert len(accesslog) == 1
    assert accesslog[0]['access_type'] == 'user_login'

    # get access log report of certain subject
    project = data_builder.create_project()
    r = as_admin.post('/sessions', json={
        'project': project,
        'label': 'test-accesslog-session',
        'timestamp': '1979-01-01T00:00:00+00:00',
        'subject': {'code': 'compliant5'}
    })
    assert r.ok
    session = r.json()['_id']

    # In order to have two logs of this subject (POST does not create a log)
    r = as_admin.get('/sessions/' + session)
    assert r.ok
    session = r.json()['_id']
    r = as_admin.get('/sessions/' + session)
    assert r.ok

    r = as_admin.get('/report/accesslog', params={'subject': 'compliant5'})
    assert r.ok
    for count,log in enumerate(r.json(), start = 1):
        assert log.get('context', {}).get('subject', {}).get('label') == 'compliant5'
    assert count == 2
    r = as_admin.delete('/sessions/' + session)
    data_builder.delete_project(project, recursive=True)

    # get access log report of certain access types
    r = as_admin.get('/report/accesslog', params={'access_type': ['user_login', 'view_container']})
    assert r.ok
    ul, vc = False, False

    # test that each item in log is either view_container or user_login
    for log in r.json():
        assert log.get('access_type') in ['user_login', 'view_container']
        if log.get('access_type') == 'user_login':
            ul = True
        elif log.get('access_type') == 'view_container':
            vc = True
    assert ul and vc

    # Download .csv file
    r = as_admin.get('/report/accesslog', params={'csv': 'true'})
    assert r.ok

    # Create new project with same subject name
    project2 = data_builder.create_project()
    r = as_admin.post('/sessions', json={
        'project': project2,
        'label': 'test-accesslog-session-2',
        'timestamp': '1979-01-01T00:00:00+00:00',
        'subject': {'code': 'compliant5'}
    })
    assert r.ok
    session2 = r.json()['_id']

    r = as_admin.delete('/sessions/' + session2)
    data_builder.delete_project(project2, recursive=True)

    # get access log report project filter
    r = as_admin.get('/report/accesslog', params={'project':project2, 'subject': 'compliant5'})
    assert r.ok

    for log in r.json():
        assert log.get('context',{}).get('session',{}).get('label') != 'test-accesslog-session'

    r.content[0][:3] == '_id'

    # get the access types
    r = as_admin.get('/report/accesslog/types')
    assert r.ok
    assert r.json() == AccessTypeList


def test_usage_report(data_builder, file_form, as_user, as_admin):
    # try to get usage report as user
    r = as_user.get('/report/usage', params={'type': 'month'})
    assert r.status_code == 403

    # try to get usage report w/o type
    r = as_admin.get('/report/usage')
    assert r.status_code == 400

    # try to get usage report w/ invalid date filter (end < start)
    r = as_admin.get('/report/usage', params={
        'type': 'month', 'start_date': tomorrow_ts, 'end_date': yesterday_ts
    })
    assert r.status_code == 400

    # get month-aggregated usage report
    r = as_admin.get('/report/usage', params={'type': 'month'})
    assert r.ok
    usage = r.json()
    assert len(usage) == 1
    assert (usage[0]['year'], usage[0]['month']) == (str(today.year), str(today.month))
    print usage
    assert usage[0]['session_count'] == 0
    assert usage[0]['file_mbs'] == 0
    assert usage[0]['gear_execution_count'] == 0

    # get project-aggregated usage report
    r = as_admin.get('/report/usage', params={'type': 'project'})
    assert r.ok
    assert len(r.json()) == 0

    project = data_builder.create_project(label='usage')
    session = data_builder.create_session()
    acquisition = data_builder.create_acquisition()
    analysis = as_admin.post('/sessions/' + session + '/analyses', files=file_form(meta={'label': 'test'})).json()['_id']
    as_admin.post('/acquisitions/' + acquisition + '/files', files=file_form('input.csv'))
    job = data_builder.create_job(inputs={'usage': {'type': 'acquisition', 'id': acquisition, 'name': 'input.csv'}})
    as_admin.get('/jobs/next', params={'root': 'true'})
    as_admin.post('/engine',
        params={'root': 'true', 'level': 'analysis', 'id': analysis, 'job': job},
        files=file_form('output.csv', meta={'type': 'text', 'value': {'label': 'test'}})
    )
    as_admin.put('/jobs/' + job, params={'root': 'true'}, json={'state': 'complete'})

    # get month-aggregated usage report
    monthrange = calendar.monthrange(today.year, today.month)
    start_ts = ts_format.format(today.replace(day=1))
    end_ts = ts_format.format(today.replace(day=monthrange[1], hour=23, minute=59, second=59))
    r = as_admin.get('/report/usage', params={
        'type': 'month', 'start_date': start_ts, 'end_date': end_ts
    })
    assert r.ok
    usage = r.json()
    assert len(usage) == 1
    assert (usage[0]['year'], usage[0]['month']) == (str(today.year), str(today.month))
    assert usage[0]['session_count'] == 1
    assert usage[0]['file_mbs'] > 0
    # TODO test gear exec counter
    assert usage[0]['gear_execution_count'] == 1

    # get project-aggregated usage report
    r = as_admin.get('/report/usage', params={
        'type': 'project', 'start_date': yesterday_ts, 'end_date': tomorrow_ts
    })
    assert r.ok
    usage = r.json()
    assert len(usage) == 1
    assert usage[0]['project']['label'] == 'usage'
    assert usage[0]['session_count'] == 1
    assert usage[0]['file_mbs'] > 0
    assert usage[0]['gear_execution_count'] == 1

    # Test if empty project breaks Usage report
    group = data_builder.create_group()
    r = as_admin.post('/projects', params={'inherit': 'false'}, json={'label': 'project2', 'group': group, 'phi' : True})
    assert r.ok
    project = r.json()['_id']

    # get project-aggregated usage report
    r = as_admin.get('/report/usage', params={'type': 'project'})
    assert r.ok

    # delete project
    r= as_admin.delete('/projects/' + project)
    assert r.ok
