import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)


def test_rule_access(with_a_group_and_a_project, as_user):
    data = with_a_group_and_a_project

    r = as_user.get('/projects/' + data.project_id + '/rules')
    assert r.ok

    r = as_user.post('/projects/' + data.project_id + '/rules', json={
        'alg': 'my-gear-name',

        'name': 'whatever',

        'any': [],

        'all': [
            {
                'type': 'file.type',
                'value': 'nifti'
            },
            {
                'type': 'file.measurements',
                'value': 'functional'
            }
        ]
    })
    assert r.ok

    r = as_user.get('/projects/' + data.project_id + '/rules')
    assert r.ok
    assert r.json()[0]['alg'] == 'my-gear-name'
