import os
import sys

import attrdict
import bson
import pytest


@pytest.fixture(scope='function')
def undelete(mocker):
    """Enable importing from `bin` and return `undelete.undelete`."""
    bin_path = os.path.join(os.getcwd(), 'bin')
    mocker.patch('sys.path', [bin_path] + sys.path)
    import undelete
    return undelete.undelete


@pytest.yield_fixture(scope='function')
def containers(data_builder, as_admin, file_form, api_db):
    """Populate DB with test dataset including deleted and non-deleted entries."""
    p_1 = data_builder.create_project()
    s_1_1 = data_builder.create_session(project=p_1)
    c_1_1_1 = data_builder.create_collection()
    an_1_1_1 = as_admin.post('/sessions/' + s_1_1 + '/analyses', files=file_form(
        'analysis.csv', meta={'label': 'no-job', 'inputs': [{'name': 'analysis.csv'}]})).json()['_id']
    ac_1_1_1 = data_builder.create_acquisition(session=s_1_1)
    ac_1_1_2 = data_builder.create_acquisition(session=s_1_1)
    s_1_2 = data_builder.create_session(project=p_1)
    ac_1_2_1 = data_builder.create_acquisition(session=s_1_2)
    p_2 = data_builder.create_project()
    s_2_1 = data_builder.create_session(project=p_2)
    ac_2_1_1 = data_builder.create_acquisition(session=s_2_1)
    assert as_admin.post('/acquisitions/' + ac_1_1_1 + '/files', files=file_form('f_1_1_1_1')).ok
    assert as_admin.post('/acquisitions/' + ac_1_1_1 + '/files', files=file_form('f_1_1_1_2')).ok
    assert as_admin.post('/acquisitions/' + ac_2_1_1 + '/files', files=file_form('f_2_1_1_1')).ok
    assert as_admin.post('/acquisitions/' + ac_1_1_1 + '/files', files=file_form('f_1_1_1_1')).ok

    assert as_admin.delete('/sessions/' + s_1_1 + '/analyses/' + an_1_1_1).ok
    assert as_admin.delete('/collections/' + c_1_1_1).ok
    assert as_admin.delete('/acquisitions/' + ac_1_1_1 + '/files/f_1_1_1_1').ok
    assert as_admin.delete('/acquisitions/' + ac_1_1_1).ok
    assert as_admin.delete('/sessions/' + s_1_1).ok
    assert as_admin.delete('/projects/' + p_1).ok

    containers = attrdict.AttrDict(
        p_1=p_1,
        s_1_1=s_1_1,
        c_1_1_1=c_1_1_1,
        an_1_1_1=an_1_1_1,
        ac_1_1_1=ac_1_1_1,
        ac_1_1_2=ac_1_1_2,
        s_1_2=s_1_2,
        ac_1_2_1=ac_1_2_1,
        p_2=p_2,
        s_2_1=s_2_1,
        ac_2_1_1=ac_2_1_1,
    )

    def is_deleted(cont_key, filename=None):
        cont_name = {'p': 'projects',
                     's': 'sessions',
                     'ac': 'acquisitions',
                     'an': 'analyses',
                     'c': 'collections',
                    }[cont_key.split('_')[0]]
        url = '/{}/{}'.format(cont_name, containers[cont_key])
        if filename is None:
            return as_admin.get(url).status_code == 404
        else:
            return as_admin.get(url + '/files/' + filename).status_code == 404

    containers['is_deleted'] = is_deleted
    yield containers
    api_db.analyses.delete_one({'_id': bson.ObjectId(an_1_1_1)})


def test_undelete_noop(undelete, containers):
    undelete('projects', containers.p_2)
    undelete('sessions', containers.s_2_1)
    undelete('acquisitions', containers.ac_2_1_1)
    undelete('acquisitions', containers.ac_2_1_1, filename='f_2_1_1_1')


def test_undelete_scope(undelete, containers, as_admin, api_db):
    assert containers.is_deleted('p_1')
    assert containers.is_deleted('s_1_1')
    assert containers.is_deleted('s_1_2')
    undelete('projects', containers.p_1)
    assert not containers.is_deleted('p_1')
    assert containers.is_deleted('s_1_1')
    assert not containers.is_deleted('s_1_2')

    assert containers.is_deleted('s_1_1')
    assert containers.is_deleted('ac_1_1_1')
    assert containers.is_deleted('ac_1_1_2')
    undelete('sessions', containers.s_1_1)
    assert not containers.is_deleted('s_1_1')
    assert containers.is_deleted('ac_1_1_1')
    assert not containers.is_deleted('ac_1_1_2')

    assert containers.is_deleted('ac_1_1_1')
    undelete('acquisitions', containers.ac_1_1_1)
    assert not containers.is_deleted('ac_1_1_1')

    assert containers.is_deleted('ac_1_1_1', filename='f_1_1_1_1')
    undelete('acquisitions', containers.ac_1_1_1, filename='f_1_1_1_1')
    assert not containers.is_deleted('ac_1_1_1', filename='f_1_1_1_1')

    assert containers.is_deleted('c_1_1_1')
    undelete('collections', containers.c_1_1_1)
    assert not containers.is_deleted('c_1_1_1')

    assert containers.is_deleted('an_1_1_1')
    undelete('analyses', containers.an_1_1_1)
    assert not containers.is_deleted('an_1_1_1')


def test_undelete_options(undelete, containers):
    with pytest.raises(RuntimeError, match=r'use `--include-parents`'):
        undelete('acquisitions', containers.ac_1_1_1, filename='f_1_1_1_1')

    undelete('acquisitions', containers.ac_1_1_1, filename='f_1_1_1_1', include_parents=True)
    assert not containers.is_deleted('p_1')
    assert containers.is_deleted('s_1_2')

    undelete('projects', containers.p_1)
    assert containers.is_deleted('s_1_2')

    undelete('projects', containers.p_1, always_propagate=True)
    assert not containers.is_deleted('s_1_2')
