import attrdict
import base64
import copy
import datetime
import json
import os

import pymongo
import pytest
import requests


# load required envvars w/ the same name
SCITRAN_CORE_DRONE_SECRET = os.environ['SCITRAN_CORE_DRONE_SECRET']
SCITRAN_PERSISTENT_DB_LOG_URI = os.environ['SCITRAN_PERSISTENT_DB_LOG_URI']
SCITRAN_PERSISTENT_DB_URI = os.environ['SCITRAN_PERSISTENT_DB_URI']
SCITRAN_SITE_API_URL = os.environ['SCITRAN_SITE_API_URL']

# create api keys for users
SCITRAN_ADMIN_API_KEY = base64.encodestring(os.urandom(32))[:-1]
SCITRAN_USER_API_KEY = base64.encodestring(os.urandom(32))[:-1]


@pytest.fixture(scope='session')
def api_db():
    """Return mongo client for the api db"""
    return pymongo.MongoClient(SCITRAN_PERSISTENT_DB_URI).get_default_database()


@pytest.fixture(scope='session')
def log_db():
    """Return mongo client for the log db"""
    return pymongo.MongoClient(SCITRAN_PERSISTENT_DB_LOG_URI).get_default_database()


@pytest.fixture(scope='session')
def as_drone():
    """Return requests session with drone access"""
    session = BaseUrlSession()
    session.headers.update({
        'X-SciTran-Method': 'bootstrapper',
        'X-SciTran-Name': 'Bootstrapper',
        'X-SciTran-Auth': SCITRAN_CORE_DRONE_SECRET,
    })
    return session


@pytest.fixture(scope='session')
def bootstrap_users(as_drone):
    """Create admin and non-admin users with api keys"""
    data_builder = DataBuilder(as_drone)
    data_builder.create_user(_id='admin@user.com', api_key=SCITRAN_ADMIN_API_KEY, root=True)
    data_builder.create_user(_id='user@user.com', api_key=SCITRAN_USER_API_KEY, root=False)


@pytest.fixture(scope='session')
def as_root(bootstrap_users):
    """Return requests session using admin api key and root=true"""
    session = BaseUrlSession()
    session.headers.update({'Authorization': 'scitran-user {}'.format(SCITRAN_ADMIN_API_KEY)})
    session.params.update({'root': 'true'})
    return session


@pytest.fixture(scope='session')
def as_admin(bootstrap_users):
    """Return requests session using admin api key"""
    session = BaseUrlSession()
    session.headers.update({'Authorization': 'scitran-user {}'.format(SCITRAN_ADMIN_API_KEY)})
    return session


@pytest.fixture(scope='session')
def as_user(bootstrap_users):
    """Return requests session using user api key"""
    session = BaseUrlSession()
    session.headers.update({'Authorization': 'scitran-user {}'.format(SCITRAN_USER_API_KEY)})
    return session


@pytest.fixture(scope='function')
def as_public():
    """Return requests session without authentication"""
    return BaseUrlSession()


@pytest.yield_fixture(scope='session')
def session_data_builder(as_root):
    """Yield DataBuilder instance (per session)"""
    data_builder = DataBuilder(as_root)
    yield data_builder
    data_builder.teardown()


@pytest.yield_fixture(scope='module')
def module_data_builder(as_root):
    """Yield DataBuilder instance (per module)"""
    data_builder = DataBuilder(as_root)
    yield data_builder
    data_builder.teardown()


@pytest.yield_fixture(scope='function')
def function_data_builder(as_root):
    """Yield DataBuilder instance (per test)"""
    data_builder = DataBuilder(as_root)
    yield data_builder
    data_builder.teardown()


@pytest.fixture(scope='session')
def session_state(session_data_builder):
    builder = session_data_builder
    return attrdict.AttrDict(
        gear        = builder.create_gear(),
        group       = builder.create_group(),
        project     = builder.create_project(),
        session     = builder.create_session(),
        acquisition = builder.create_acquisition(),
    )


class BaseUrlSession(requests.Session):
    """Requests session subclass using core api's base url"""

    def __init__(self, *args, **kwargs):
        super(BaseUrlSession, self).__init__(*args, **kwargs)
        self.base_url = SCITRAN_SITE_API_URL

    def request(self, method, url, **kwargs):
        return super(BaseUrlSession, self).request(method, self.base_url + url, **kwargs)


class DataBuilder(object):
    api_db = api_db()
    defaults = {
        'gear': {
            'category': 'converter',
            'gear': {
                'name': 'test-gear',
                'inputs': {
                    'text files (max 100K)': {
                        'base': 'file',
                        'name': {'pattern': '^.*.txt$'},
                        'size': {'maximum': 100000}
                    }
                },
                'maintainer': 'test',
                'description': 'test',
                'license': 'BSD-2-Clause',
                'author': 'test',
                'url': 'https://test.test',
                'label': 'test',
                'flywheel': '0',
                'source': 'https://test.test',
                'version': '0.0.1',
                'config': {},
            },
            'exchange': {
                'git-commit': 'aex',
                'rootfs-hash': 'sha384:oy',
                'rootfs-url': 'https://test.test'
            }
        },
        'job': {},
        'user': {'_id': 'test-user', 'firstname': 'test', 'lastname': 'user'},
        'group': {'_id': 'test-group'},
        'project': {'label': 'test-project', 'public': True},
        'session': {'label': 'test-session', 'public': True},
        'acquisition': {'label': 'test-acquisition', 'public': True},
    }
    parent_cont = {
        'project':     'group',
        'session':     'project',
        'acquisition': 'session',
    }

    def __init__(self, session):
        self.session = session
        self.orig_db_state = self.get_db_state()
        self.resources_created = []

    def __getattr__(self, name):
        if name.startswith('create_'):
            resource = name.replace('create_', '', 1)
            def create_resource(**kwargs):
                return self.create(resource, **kwargs)
            return create_resource
        raise AttributeError

    def get_db_state(self):
        db_state = {}
        for collection in self.defaults:
            cursor = self.api_db[collection].find({}, {'_id': 1})
            db_state[collection] = set(doc['_id'] for doc in cursor)
        return db_state

    def create(self, resource, **kwargs):
        payload = copy.deepcopy(self.defaults.get(resource, {}))
        payload.update(kwargs)
        if resource in ('group', 'project', 'session', 'acquisition'):
            parent_cont = self.parent_cont.get(resource)
            if parent_cont and parent_cont not in payload:
                payload[parent_cont] = self.get_or_create(parent_cont)
        elif resource == 'job' and 'gear_id' not in payload:
            payload['gear_id'] = self.get_or_create('gear')
        elif resource == 'user':
            user_api_key = payload.pop('api_key', None)
        create_url = '/' + resource + 's'
        if resource == 'gear':
            create_url += '/' + payload['gear']['name']
        elif resource == 'job':
            create_url += '/add'
        r = self.session.post(create_url, json=payload)
        assert r.ok
        _id = r.json()['_id']
        self.resources_created.append((resource, _id))
        if resource == 'user' and user_api_key:
            self.api_db.users.update_one(
                {'_id': _id},
                {'$set': {
                    'api_key': {
                        'key': user_api_key,
                        'created': datetime.datetime.utcnow()
                    }
                }}
            )
        return _id

    def get_or_create(self, resource):
        for resource_, _id in self.resources_created:
            if resource == resource_:
                return _id
        return self.create(resource)

    def teardown(self):
        for resource, _id in reversed(self.resources_created):
            self.delete_recursively(resource, _id)
        assert self.get_db_state() == self.orig_db_state

    def delete_recursively(self, resource, _id):
        if resource in self.parent_cont.values():
            child_cont = next(c for c in self.parent_cont if self.parent_cont[c] == resource)
            r = self.session.get('/{}s/{}/{}s'.format(resource, _id, child_cont))
            assert r.ok
            for child in r.json():
                self.delete_recursively(child_cont, child['_id'])
        elif resource == 'gear':
            self.api_db.jobs.delete_many({'gear_id': _id})
        r = self.session.delete('/{}/{}'.format(resource, _id))
        assert r.ok or r.status_code == 404
