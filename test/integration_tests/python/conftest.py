import binascii
import copy
import datetime
import json
import logging
import os

import attrdict
import bson
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
def bootstrap_users(as_drone):
    """Create admin and non-admin users with api keys"""
    data_builder = DataBuilder(as_drone)
    data_builder.create_user(_id='admin@user.com', api_key=SCITRAN_ADMIN_API_KEY, root=True)
    data_builder.create_user(_id='user@user.com', api_key=SCITRAN_USER_API_KEY)
    return data_builder


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
def api_db():
    """Return mongo client for the api db"""
    return pymongo.MongoClient(SCITRAN_PERSISTENT_DB_URI).get_default_database()


@pytest.fixture(scope='session')
def log_db():
    """Return mongo client for the log db"""
    return pymongo.MongoClient(SCITRAN_PERSISTENT_DB_LOG_URI).get_default_database()


@pytest.yield_fixture(scope='function')
def data_builder(as_root, randstr):
    """Yield DataBuilder instance (per test)"""
    # NOTE currently there's only a single data_builder for simplicity which
    # uses as_root - every resource is created/owned by the admin user
    data_builder = DataBuilder(as_root, randstr=randstr)
    yield data_builder
    data_builder.teardown()


@pytest.fixture(scope='function')
def default_payload():
    """Return default test resource creation payloads"""
    return attrdict.AttrDict({
        'user': {'firstname': 'test', 'lastname': 'user'},
        'group': {},
        'project': {'public': True},
        'session': {'public': True},
        'acquisition': {'public': True},
        'collection': {},
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
        'job': {'inputs': {}},
    })


@pytest.fixture(scope='function')
def randstr(request):

    def randstr():
        """Return random string prefixed with test module and function name"""
        # NOTE Useful for generating required unique document fields in data_builder
        # or in tests directly by using the fixture. Uses hex strings as each of
        # those fields (user._id, group._id, gear.gear.name) support [a-z0-9]

        def clean(test_name):
            return test_name.lower().replace('test_', '').rstrip('_').replace('_', '-')

        module = clean(request.module.__name__)
        function = clean(request.function.__name__)
        prefix = module + '-' + function
        return prefix[:21] + '-' + binascii.hexlify(os.urandom(5))

    return randstr


@pytest.fixture(scope='session')
def file_form():

    def file_form(*files, **kwargs):
        """Return multipart/form-data for file upload requests"""
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

    return file_form


@pytest.fixture(scope='session')
def merge_dict():

    def merge_dict(a, b):
        """Merge two dicts into the first recursively"""
        for key, value in b.iteritems():
            if key in a and isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dict(a[key], b[key])
            else:
                a[key] = b[key]

    return merge_dict


@pytest.fixture(scope='module')
def log(request):
    """Return logger for the test module for easy logging from tests"""
    log = logging.getLogger(request.module.__name__)
    log.addHandler(logging.StreamHandler())
    return log


@pytest.fixture(scope='function')
def with_user(data_builder, randstr, as_public):
    """Return AttrDict with new user, api-key and api-accessor"""
    api_key = randstr()
    user = data_builder.create_user(api_key=api_key, root=True)
    session = copy.deepcopy(as_public)
    session.headers.update({'Authorization': 'scitran-user ' + api_key})
    return attrdict.AttrDict(user=user, api_key=api_key, session=session)


class BaseUrlSession(requests.Session):
    """Requests session subclass using core api's base url"""
    def request(self, method, url, **kwargs):
        return super(BaseUrlSession, self).request(method, SCITRAN_SITE_API_URL + url, **kwargs)


class DataBuilder(object):
    child_to_parent = {
        'project':     'group',
        'session':     'project',
        'acquisition': 'session',
    }
    parent_to_child = {parent: child for child, parent in child_to_parent.items()}

    def __init__(self, session, randstr=lambda: binascii.hexlify(os.urandom(10))):
        self.session = session
        self.randstr = randstr
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

        # merge any kwargs on top of the default payload
        payload = copy.deepcopy(_default_payload[resource])
        _merge_dict(payload, kwargs)

        # add missing required unique fields using randstr
        # such fields are: [user._id, group._id, gear.gear.name]
        if resource == 'user' and '_id' not in payload:
            payload['_id'] = self.randstr() + '@user.com'
        if resource == 'group' and '_id' not in payload:
            payload['_id'] = self.randstr()
        if resource == 'gear' and 'name' not in payload['gear']:
            payload['gear']['name'] = self.randstr()

        # add missing label fields using randstr
        # such fields are: [project.label, session.label, acquisition.label]
        if resource in self.child_to_parent and 'label' not in payload:
            payload['label'] = self.randstr()

        # add missing parent container when creating child container
        if resource in self.child_to_parent:
            parent = self.child_to_parent[resource]
            if parent not in payload:
                payload[parent] = self.get_or_create(parent)

        # add missing gear when creating job
        if resource == 'job' and 'gear_id' not in payload:
            payload['gear_id'] = self.get_or_create('gear')

        # put together the create url to post to
        create_url = '/' + resource + 's'
        if resource == 'gear':
            create_url += '/' + payload['gear']['name']
        if resource == 'job':
            create_url += '/add'

        # handle user api keys (they are set via mongo directly)
        if resource == 'user':
            user_api_key = payload.pop('api_key', None)

        # create resource
        r = self.session.post(create_url, json=payload)
        if not r.ok:
            raise Exception(
                'DataBuilder failed to create {}: {}\n'
                'Payload was:\n{}'.format(resource, r.json()['message'], payload))
        _id = r.json()['_id']

        # inject api key if it was provided
        if resource == 'user' and user_api_key:
            _api_db.users.update_one(
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

    def get_or_create(self, resource):
        """Return first _id from self.resources for type `resource` (Create if not found)"""
        for resource_, _id in self.resources:
            if resource == resource_:
                return _id
        return self.create(resource)

    def teardown(self):
        """Delete resources created with this DataBuilder from self.resources"""
        for resource, _id in reversed(self.resources):
            self.delete(resource, _id)

    def delete(self, resource, _id, recursive=False):
        """Delete resource from mongodb by _id"""
        if bson.ObjectId.is_valid(_id):
            _id = bson.ObjectId(_id)
        if recursive and resource in self.parent_to_child:
            child_cont = self.parent_to_child[resource]
            for child in _api_db[child_cont + 's'].find({resource: _id}, {'_id': 1}):
                self.delete(child_cont, child['_id'], recursive=recursive)
        if resource == 'gear':
            _api_db.jobs.remove({'gear_id': str(_id)})
        _api_db[resource + 's'].remove({'_id': _id})


# Store return values of pytest fixtures that are also used by DataBuilder
# as "private singletons" in the module. This seemed the least confusing.
_default_payload = default_payload()
_api_db = api_db()
_merge_dict = merge_dict()
