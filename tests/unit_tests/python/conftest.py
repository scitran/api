import binascii
import bson
import copy
import datetime
import logging
import os

import attrdict
import mock
import mongomock
import pytest
import webapp2

import api.config

SCITRAN_CORE_DRONE_SECRET = os.environ['SCITRAN_CORE_DRONE_SECRET']


@pytest.fixture(scope='session')
def as_drone(app):
    """Return ApiAccessor with drone access"""
    return ApiAccessor(app, headers={
        'X-SciTran-Method': 'bootstrapper',
        'X-SciTran-Name': 'Bootstrapper',
        'X-SciTran-Auth': SCITRAN_CORE_DRONE_SECRET,
    })


@pytest.fixture(scope='session')
def as_public(app):
    """Return ApiAccessor without authentication"""
    return ApiAccessor(app)


@pytest.fixture(scope='session')
def api_db(app):
    """Return mongo client mock for the api db"""
    return api.config.db


@pytest.fixture(scope='session')
def log_db(app):
    """Return mongo client mock for the log db"""
    return api.config.log_db


@pytest.fixture(scope='session')
def es(app):
    """Return Elasticsearch mock (MagickMock instance)"""
    return api.config.es


@pytest.yield_fixture(scope='session')
def app():
    """Return api instance that uses mocked os.environ, ElasticSearch and MongoClient"""
    test_env = {
        'SCITRAN_CORE_DRONE_SECRET': SCITRAN_CORE_DRONE_SECRET,
        'TERM': 'xterm', # enable terminal features - useful for pdb sessions
    }
    env_patch = mock.patch.dict(os.environ, test_env, clear=True)
    env_patch.start()
    es_patch = mock.patch('elasticsearch.Elasticsearch')
    es_patch.start()
    mongo_patch = mock.patch('pymongo.MongoClient', new=mongomock.MongoClient)
    mongo_patch.start()
    # NOTE db and log_db is created at import time in api.config
    # reloading the module is needed to use the mocked MongoClient

    # Hack because of the containerhandler's import time instantiation
    # with this the containerhandler will use the same mock db instance
    import api.config
    reload(api.config)
    import api.web.start

    yield api.web.start.app_factory()
    mongo_patch.stop()
    es_patch.stop()
    env_patch.stop()


@pytest.fixture(scope='session')
def config(app):
    """Return app config accessor"""
    # NOTE depends on the app fixture as it's reloading the config module
    # NOTE the config fixture is session scoped (consider parallel tests)
    # NOTE use dict notation for assignment (eg `config['key'] = 'v'` - AttrDict limitation)
    return attrdict.AttrDict(api.config.__config)


@pytest.fixture(scope='module')
def log(request):
    """Return logger for the test module for easy logging from tests"""
    log = logging.getLogger(request.module.__name__)
    log.addHandler(logging.StreamHandler())
    return log


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


@pytest.yield_fixture(scope='function')
def data_builder(as_drone, api_db, randstr):
    """Yield DataBuilder instance (per test)"""
    # NOTE currently there's only a single data_builder for simplicity which
    # uses as_root - every resource is created/owned by the admin user
    data_builder = DataBuilder(as_drone, api_db, randstr=randstr)
    yield data_builder
    data_builder.teardown()


class DataBuilder(object):
    child_to_parent = {
        'project':     'group',
        'session':     'project',
        'acquisition': 'session',
    }
    parent_to_child = {parent: child for child, parent in child_to_parent.items()}

    def __init__(self, session, api_db, randstr=lambda: binascii.hexlify(os.urandom(10))):
        self.session = session
        self.api_db = api_db
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
        if resource == 'collection' and 'label' not in payload:
            payload['label'] = self.randstr()

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

            # create file inputs for each job input on gear
            gear_inputs = {}
            for i in payload.get('inputs', {}).keys():
                gear_inputs[i] = {'base': 'file'}

            gear_doc = _default_payload['gear']['gear']
            gear_doc['inputs'] = gear_inputs
            payload['gear_id'] = self.create('gear', gear=gear_doc)

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
                'Payload was:\n{}'.format(resource, r.json['message'], payload))
        _id = r.json['_id']

        # inject api key if it was provided
        if resource == 'user' and user_api_key:
            self.api_db.apikeys.insert_one({
                '_id': user_api_key,
                'created': datetime.datetime.utcnow(),
                'last_seen': None,
                'type': 'user',
                'uid': _id
            })

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
            for child in self.api_db[child_cont + 's'].find({resource: _id}, {'_id': 1}):
                self.delete(child_cont, child['_id'], recursive=recursive)
        if resource == 'gear':
            self.api_db.jobs.remove({'gear_id': str(_id)})
        self.api_db[resource + 's'].remove({'_id': _id})


# Store return values of pytest fixtures that are also used by DataBuilder
# as "private singletons" in the module. This seemed the least confusing.
_default_payload = default_payload()
_merge_dict = merge_dict()


class ApiAccessor(object):
    def __init__(self, app, **defaults):
        self.app = app
        self.defaults = defaults

    def __getattr__(self, name):
        """Return convenience HTTP method for `name`"""
        if name in ('head', 'get', 'post', 'put', 'delete'):
            def http_method(path, **kwargs):
                # NOTE using WebOb requests in unit tests is fundamentally different
                # to using a requests.Session in integration tests. See also:
                # http://webapp2.readthedocs.io/en/latest/guide/testing.html#app-get-response
                # https://github.com/Pylons/webob/blob/master/webob/request.py
                for key, value in self.defaults.items():
                    kwargs.setdefault(key, value)
                kwargs['method'] = name.upper()
                response = self.app.get_response('/api' + path, **kwargs)
                response.ok = response.status_code == 200
                return response
            return http_method
        raise AttributeError
