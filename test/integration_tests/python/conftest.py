import base64
import binascii
import copy
import datetime
import json
import os

import attrdict
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


@pytest.fixture(scope='session', autouse=True)
def bootstrap_users(api_db, as_drone):
    """Create admin and non-admin users with api keys"""
    data_builder = DataBuilder(api_db, as_drone)
    data_builder.create_user(_id='admin@user.com', api_key=SCITRAN_ADMIN_API_KEY, root=True)
    data_builder.create_user(_id='user@user.com', api_key=SCITRAN_USER_API_KEY)


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


_default_payload = attrdict.AttrDict({
    'user': {'firstname': 'test', 'lastname': 'user'},
    'group': {},
    'project': {'label': 'test-project', 'public': True},
    'session': {'label': 'test-session', 'public': True},
    'acquisition': {'label': 'test-acquisition', 'public': True},
    'gear': {
        'category': 'converter',
        'gear': {
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
})

@pytest.fixture(scope='function')
def default_payload():
    """Return default test resource creation payloads"""
    return copy.deepcopy(_default_payload)


@pytest.yield_fixture(scope='function')
def data_builder(api_db, as_root):
    """Yield DataBuilder instance (per test)"""
    data_builder = DataBuilder(api_db, as_root)
    yield data_builder
    data_builder.teardown()


class BaseUrlSession(requests.Session):
    """Requests session subclass using core api's base url"""

    def __init__(self, *args, **kwargs):
        super(BaseUrlSession, self).__init__(*args, **kwargs)
        self.base_url = SCITRAN_SITE_API_URL

    def request(self, method, url, **kwargs):
        return super(BaseUrlSession, self).request(method, self.base_url + url, **kwargs)


class DataBuilder(object):
    child_to_parent = {
        'project':     'group',
        'session':     'project',
        'acquisition': 'session',
    }

    def __init__(self, api_db, session):
        self.api_db = api_db
        self.session = session
        self.resources = []

    def __getattr__(self, name):
        """Return resource specific create_* or delete_* method"""
        if name.startswith('create_') or name.startswith('delete_'):
            method, resource = name.split('_', 1)
            def resource_method(*args, **kwargs):
                return getattr(self, method)(resource, *args, **kwargs)
            return resource_method
        raise AttributeError

    def create(self, resource, **kwargs):
        payload = copy.deepcopy(_default_payload[resource])
        self.merge_dict(payload, kwargs)

        if resource == 'user':
            if '_id' not in payload:
                payload['_id'] = 'test-user-{}@user.com'.format(self.get_random_hex())
            user_api_key = payload.pop('api_key', None)
        if resource == 'group':
            if '_id' not in payload:
                payload['_id'] = 'test-group-{}'.format(self.get_random_hex())
        if resource in self.child_to_parent:
            parent = self.child_to_parent[resource]
            if parent not in payload:
                payload[parent] = self.get_or_create(parent)
        if resource == 'gear':
            if 'name' not in payload['gear']:
                payload['gear']['name'] = 'test-gear-{}'.format(self.get_random_hex())

        create_url = '/' + resource + 's'
        if resource == 'gear':
            create_url += '/' + payload['gear']['name']

        r = self.session.post(create_url, json=payload)
        assert r.ok
        _id = r.json()['_id']

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
        self.resources.append((resource, _id))
        return _id

    @staticmethod
    def merge_dict(a, b):
        """Merge two dicts into the first recursively"""
        for key, value in b.iteritems():
            if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
                merge(a[key], b[key])
            else:
                a[key] = b[key]

    @staticmethod
    def get_random_hex():
        """Return random hex string"""
        return binascii.hexlify(os.urandom(10))

    def get_or_create(self, resource):
        for resource_, _id in self.resources:
            if resource == resource_:
                return _id
        return self.create(resource)

    def teardown(self, recursive=False):
        for resource, _id in reversed(self.resources):
            self.delete(resource, _id, recursive=recursive)

    def delete(self, resource, _id, recursive=False):
        if resource in self.child_to_parent.values() and recursive:
            child_cont = next(c for c in self.child_to_parent
                                if self.child_to_parent[c] == resource)
            for child_id in self.api_db[child_cont].find({resource: _id}, {'_id': 1}):
                self.delete(child_cont, child_id)
        if resource == 'gear':
            self.api_db.jobs.delete_many({'gear_id': _id})
        self.api_db[resource].delete_one({'_id': _id})
