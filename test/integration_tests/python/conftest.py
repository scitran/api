import json
import os
import time

import pytest
import pymongo
import requests


@pytest.fixture(scope="session")
def bunch():
    class BunchFactory:
        def create():
            return type('Bunch', (), {})
        create = staticmethod(create)

    return BunchFactory()


@pytest.fixture(scope="module")
def db():
    mongo_path = os.environ.get('MONGO_PATH', 'mongodb://localhost:9001/scitran')
    return pymongo.MongoClient(mongo_path).get_default_database()


@pytest.fixture(scope="module")
def base_url():
    return os.environ.get('BASE_URL', 'http://localhost:8080/api')


class RequestsAccessor(object):
    def __init__(self, base_url, default_params=None, default_headers=None):
        self.base_url = base_url
        if default_params is None:
            default_params = {}
        self.default_params = default_params
        if default_headers is None:
            default_headers = {}
        self.default_headers = default_headers

    def _get_params(self, **kwargs):
        params = self.default_params.copy()
        if ("params" in kwargs):
            params.update(kwargs["params"])
        return params

    def get_headers(self, user_headers):
        request_headers = self.default_headers.copy()
        request_headers.update(user_headers)
        return request_headers

    def get(self, url_path, **kwargs):
        url = self.get_url_from_path(url_path)
        kwargs['params'] = self._get_params(**kwargs)
        headers = self.get_headers(kwargs.get("headers", {}))
        return requests.get(url, verify=False,
                            headers=headers, **kwargs)

    def post(self, url_path, **kwargs):
        url = self.get_url_from_path(url_path)
        kwargs['params'] = self._get_params(**kwargs)
        headers = self.get_headers(kwargs.get("headers", {}))
        return requests.post(url, verify=False,
                             headers=headers, **kwargs)

    def put(self, url_path, **kwargs):
        url = self.get_url_from_path(url_path)
        kwargs['params'] = self._get_params(**kwargs)
        headers = self.get_headers(kwargs.get("headers", {}))
        return requests.put(url, verify=False,
                            headers=headers, **kwargs)

    def delete(self, url_path, **kwargs):
        kwargs['params'] = self._get_params(**kwargs)
        headers = self.get_headers(kwargs.get("headers", {}))
        url = self.get_url_from_path(url_path)
        return requests.delete(url, verify=False,
                               headers=headers, **kwargs)

    def get_url_from_path(self, path):
        return "{0}{1}".format(self.base_url, path)

@pytest.fixture(scope="module")
def api_as_admin(base_url):
    accessor = RequestsAccessor(base_url,
        {"user": "admin@user.com", "root": "true"},
        default_headers={
            "Authorization":"scitran-user XZpXI40Uk85eozjQkU1zHJ6yZHpix+j0mo1TMeGZ4dPzIqVPVGPmyfeK"
            }
        )
    return accessor


@pytest.fixture(scope="module")
def api_as_user(base_url):
    accessor = RequestsAccessor(base_url,
        {"user": "admin@user.com"},
        default_headers={
            "Authorization":"scitran-user XZpXI40Uk85eozjQkU1zHJ6yZHpix+j0mo1TMeGZ4dPzIqVPVGPmyfeK"
            }
        )
    return accessor


@pytest.fixture(scope="module")
def api_accessor(base_url):
    class RequestsAccessorWithBaseUrl(RequestsAccessor):
        def __init__(self, user_api_key):
            super(self.__class__, self).__init__(
                base_url,
                default_headers={
                    "Authorization":"scitran-user {0}".format(user_api_key)
                })

    return RequestsAccessorWithBaseUrl


@pytest.fixture()
def with_a_group_and_a_project(api_as_admin, data_builder, request, bunch):

    user_1 = 'user1@user.com'
    user_2 = 'user2@user.com'

    group_id = 'test_group_' + str(int(time.time() * 1000))
    data_builder.create_group(group_id)
    project_id = data_builder.create_project(group_id)

    def teardown_db():
        data_builder.delete_project(project_id)
        data_builder.delete_group(group_id)

    request.addfinalizer(teardown_db)

    fixture_data = bunch.create()
    fixture_data.project_id = project_id
    fixture_data.user_1 = user_1
    fixture_data.user_2 = user_2
    return fixture_data


@pytest.fixture(scope="module")
def data_builder(api_as_admin):
    class DataBuilder:

        # This function is called whenever DataBuilder.create_X() or
        # DataBuilder.delete_X() is called (those functions don't
        # actually exist). It returns a callable object that does the right
        # thing based on what X is.
        # This madness allows significantly reduced copy/paste code and more
        # readable tests.
        def __getattr__(self, name):
            parent_attribute = {
                'group': '_id',
                'project': 'group',
                'session': 'project',
                'acquisition': 'session'
            }

            # create_<container>( parent_id )
            #
            # Call the functions create_group(), create_project(), create_session(),
            # or create_acquisition(), passing in the "parent" container id as the singular
            # parameter.
            if name.startswith('create_'):
                def create_(parent_id):
                    container = name.split('create_')[1]
                    parent = parent_attribute[container]
                    api_path = '/' + container + 's'  # API paths are pluralized

                    payload = {parent: parent_id}
                    if (container != 'group'):
                        payload.update({'public': True, 'label': container + '_testing'})
                    payload = json.dumps(payload)

                    print api_path, payload
                    r = api_as_admin.post(api_path, data=payload)
                    print r.content

                    assert r.ok

                    return json.loads(r.content)['_id']
                return create_

            # delete_<container>( id )
            #
            # Call the functions delete_group(), delete_project(), delete_session(),
            # or delete_acquisition(), passing in the id as the only parameter.
            if name.startswith('delete_'):
                def delete_(id):
                    container = name.split('delete_')[1]
                    api_path = '/' + container + 's'  # API paths are pluralized
                    r = api_as_admin.delete(api_path + '/' + id)
                    assert r.ok

                return delete_
    return DataBuilder()
