def test_roothandler(as_public):
    r = as_public.get('')
    assert r.ok
    assert '<title>SciTran API</title>' in r.text


def test_schemahandler(as_public):
    r = as_public.get('/schemas/non/existent.json')
    assert r.status_code == 404

    r = as_public.get('/schemas/definitions/user.json')
    assert r.ok
    schema = r.json()
    assert all(attr in schema['definitions'] for attr in ('_id', 'firstname', 'lastname'))


def test_reporthandler(data_builder, randstr, as_admin, as_user):
    group_name = randstr()
    group = data_builder.create_group(name=group_name)
    project = data_builder.create_project()
    session = data_builder.create_session()

    # try to get site report as non-admin
    r = as_user.get('/report/site')
    assert r.status_code == 403

    # get site report
    r = as_admin.get('/report/site')
    assert r.ok

    site_report = r.json()
    group_report = next((g for g in site_report['groups'] if g['name'] == group_name), None)
    assert group_report is not None
    assert group_report['project_count'] == 1
    assert group_report['session_count'] == 1

    # try to get project report w/o perms
    r = as_user.get('/report/project', params={'projects': project})
    assert r.status_code == 403
