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
SCITRAN_ADMIN_API_KEY = binascii.hexlify(os.urandom(10))
SCITRAN_USER_API_KEY = binascii.hexlify(os.urandom(10))


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

class BaseUrlSession(requests.Session):
    """Requests session subclass using core api's base url"""

    def __init__(self, *args, **kwargs):
        super(BaseUrlSession, self).__init__(*args, **kwargs)
        self.base_url = SCITRAN_SITE_API_URL

    def request(self, method, url, **kwargs):
        return super(BaseUrlSession, self).request(method, self.base_url + url, **kwargs)


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


@pytest.fixture(scope='session')
def randstr():
    """Return random hex creator function"""
    return _randstr

def _randstr(n=10):
    """Return random hex string"""
    # NOTE Useful for generating required unique document fields in data_builder
    # or in tests directly by using the randstr fixture. Uses hex strings as each
    # of those fields (user._id, group._id, gear.gear.name) support [a-z0-9]
    return binascii.hexlify(os.urandom(n))


@pytest.fixture(scope='function')
def default_payload():
    """Return copy of default test resource creation payloads"""
    # returning copy to enable tests changing it freely
    return copy.deepcopy(_default_payload)

# default test resource creation payloads
_default_payload = attrdict.AttrDict({
    'user': {'firstname': 'test', 'lastname': 'user'},
    'group': {},
    'project': {'label': 'test-project', 'public': True},
    'session': {'label': 'test-session', 'public': True},
    'acquisition': {'label': 'test-acquisition', 'public': True},
    'gear': {
        'exchange': {
            'git-commit': 'aex',
            'rootfs-hash': 'sha384:oy',
            'rootfs-url': 'https://test.test'
        },
        'gear': {
            'author': 'test',
            'config': {},
            'description': 'test',
            'inputs': {
                'text files (max 100K)': {
                    'base': 'file',
                    'name': {'pattern': '^.*.txt$'},
                    'size': {'maximum': 100000}
                }
            },
            'label': 'test',
            'license': 'BSD-2-Clause',
            'source': 'https://test.test',
            'url': 'https://test.test',
            'version': '0.0.1',
        },
    },
})


@pytest.fixture(scope='session')
def file_form():
    """Return multipart/form-data creator"""
    return _file_form

def _file_form(*files, **kwargs):
    """Create multipart/form-data dict for file upload requests"""
    data = {}
    for i, file_ in enumerate(files):
        if isinstance(file_, str):
            file_ = (file_, 'test\ndata\n')
        data['file' + str(i + 1)] = file_
    if len(files) == 1:
        data['file'] = data.pop('file1')
    meta = kwargs.pop('meta', None)
    if meta:
        data['metadata'] = ('', json.dumps(meta))
    return data


@pytest.yield_fixture(scope='function')
def data_builder(api_db, as_root):
    """Yield DataBuilder instance (per test)"""
    data_builder = DataBuilder(api_db, as_root)
    yield data_builder
    data_builder.teardown()

class DataBuilder(object):
    child_to_parent = {
        'project':     'group',
        'session':     'project',
        'acquisition': 'session',
    }
    parent_to_child = {parent: child for child, parent in child_to_parent.items()}

    def __init__(self, api_db, session):
        self.api_db = api_db
        self.session = session
        self.resources = []

    def __getattr__(self, name):
        """Return resource specific create_* or delete_* method"""
        if name.startswith('create_') or name.startswith('delete_'):
            method, resource = name.split('_', 1)
            if resource not in _default_payload:
                raise Exception('Unknown resource type {} (from {})'.format(resource, name))
            def resource_method(*args, **kwargs):
                return getattr(self, method)(resource, *args, **kwargs)
            return resource_method
        raise AttributeError

    def create(self, resource, **kwargs):
        """Create resource in api and return it's _id"""

        # dict_merge any kwargs on top of the default payload
        payload = copy.deepcopy(_default_payload[resource])
        self.merge_dict(payload, kwargs)

        # add missing required unique fields using random strings
        # such fields are: [user._id, group._id, gear.gear.name]
        if resource == 'user':
            if '_id' not in payload:
                payload['_id'] = 'test-user-{}@user.com'.format(_randstr())
            user_api_key = payload.pop('api_key', None)
        if resource == 'group':
            if '_id' not in payload:
                payload['_id'] = 'test-group-{}'.format(_randstr())
        if resource == 'gear':
            if 'name' not in payload['gear']:
                payload['gear']['name'] = 'test-gear-{}'.format(_randstr())

        # add missing parent container when creating child container
        if resource in self.child_to_parent:
            parent = self.child_to_parent[resource]
            if parent not in payload:
                payload[parent] = self.get_or_create(parent)

        # put together the create url to post to
        create_url = '/' + resource + 's'
        if resource == 'gear':
            create_url += '/' + payload['gear']['name']

        r = self.session.post(create_url, json=payload)
        if not r.ok:
            raise Exception(
                'DataBuilder failed to create {}: {}\n'
                'Payload was:\n{}'.format(resource, r.json()['message'], payload))
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
                DataBuilder.merge_dict(a[key], b[key])
            else:
                a[key] = b[key]

    def get_or_create(self, resource):
        """Return first _id from self.resources for type `resource` (Create if not found)"""
        for resource_, _id in self.resources:
            if resource == resource_:
                return _id
        return self.create(resource)

    def teardown(self, recursive=False):
        """Delete all resources in self.resources (and children thereof, if recursive)"""
        for resource, _id in reversed(self.resources):
            self.delete(resource, _id, recursive=recursive)

    def delete(self, resource, _id, recursive=False):
        if resource in self.child_to_parent.values() and recursive:
            child_cont = self.parent_to_child[resource]
            for child_id in self.api_db[child_cont].find({resource: _id}, {'_id': 1}):
                self.delete(child_cont, child_id, recursive=recursive)
        if resource == 'gear':
            self.api_db.jobs.delete_many({'gear_id': _id})
        self.api_db[resource].delete_one({'_id': _id})
