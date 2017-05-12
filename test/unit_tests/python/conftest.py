import logging
import os

import attrdict
import mock
import mongomock
import pytest
import webapp2

import api.config
import api.web.start


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


@pytest.yield_fixture(scope='session')
def app():
    """Return api instance that uses mocked MongoClient"""
    mongo_patch = mock.patch('pymongo.MongoClient', new=mongomock.MongoClient)
    mongo_patch.start()
    # NOTE db and log_db is created at import time in api.config
    # reloading the module is needed to use the mocked MongoClient
    reload(api.config)
    yield api.web.start.app_factory()
    mongo_patch.stop()


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
