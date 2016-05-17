import bson
import datetime

from .. import base
from .. import util
from .. import config
from .. import debuginfo
from .. import validators
from ..auth import containerauth, always_ok
from ..dao import APIStorageException, containerstorage, snapshot

log = config.log


class ContainerHandler(base.RequestHandler):
    """
    This class handle operations on a generic container

    The pattern used is:
    1) load the storage class used to interact with mongo
    2) configure the permissions checker and the json payload validators
    3) validate the input payload
    4) augment the payload when appropriate
    5) exec the request (using the mongo validator and the permissions checker)
    6) check the result
    7) augment the result when needed
    8) return the result

    Specific behaviors (permissions checking logic for authenticated and not superuser users, storage interaction)
    are specified in the container_handler_configurations
    """
    use_object_id = {
        'groups': False,
        'projects': True,
        'sessions': True,
        'acquisitions': True
    }
    default_list_projection = ['files', 'notes', 'timestamp', 'timezone', 'public']

    # This configurations are used by the ContainerHandler class to load the storage,
    # the permissions checker and the json schema validators used to handle a request.
    #
    # "children_cont" represents the children container.
    # "list projection" is used to filter data in mongo.
    # "use_object_id" implies that the container ids are converted to ObjectId
    container_handler_configurations = {
        'projects': {
            'storage': containerstorage.ContainerStorage('projects', use_object_id=use_object_id['projects']),
            'permchecker': containerauth.default_container,
            'parent_storage': containerstorage.ContainerStorage('groups', use_object_id=use_object_id['groups']),
            'storage_schema_file': 'project.json',
            'payload_schema_file': 'project.json',
            'list_projection': {'metadata': 0},
            'children_cont': 'sessions'
        },
        'sessions': {
            'storage': containerstorage.ContainerStorage('sessions', use_object_id=use_object_id['sessions']),
            'permchecker': containerauth.default_container,
            'parent_storage': containerstorage.ContainerStorage('projects', use_object_id=use_object_id['projects']),
            'storage_schema_file': 'session.json',
            'payload_schema_file': 'session.json',
            'list_projection': {'metadata': 0},
            'children_cont': 'acquisitions'
        },
        'acquisitions': {
            'storage': containerstorage.ContainerStorage('acquisitions', use_object_id=use_object_id['acquisitions']),
            'permchecker': containerauth.default_container,
            'parent_storage': containerstorage.ContainerStorage('sessions', use_object_id=use_object_id['sessions']),
            'storage_schema_file': 'acquisition.json',
            'payload_schema_file': 'acquisition.json',
            'list_projection': {'metadata': 0}
        }
    }

    def __init__(self, request=None, response=None):
        super(ContainerHandler, self).__init__(request, response)

    def get(self, cont_name, **kwargs):
        _id = kwargs.pop('cid')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container= self._get_container(_id)

        permchecker = self._get_permchecker(container)
        try:
            # This line exec the actual get checking permissions using the decorator permchecker
            result = permchecker(self.storage.exec_op)('GET', _id)
        except APIStorageException as e:
            self.abort(400, e.message)
        if result is None:
            self.abort(404, 'Element not found in container {} {}'.format(storage.cont_name, _id))
        if not self.superuser_request:
            self._filter_permissions(result, self.uid, self.user_site)
        # build and insert file paths if they are requested
        if self.is_true('paths'):
            for fileinfo in result['files']:
                fileinfo['path'] = util.path_from_hash(fileinfo['hash'])
        if self.debug:
            debuginfo.add_debuginfo(self, cont_name, result)
        return result

    def _filter_permissions(self, result, uid, site):
        """
        if the user is not admin only her permissions are returned.
        """
        user_perm = util.user_perm(result.get('permissions', []), uid, site)
        if user_perm.get('access') != 'admin':
            result['permissions'] = [user_perm] if user_perm else []

    def get_all(self, cont_name, par_cont_name=None, par_id=None):
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        projection = self.config['list_projection']
        if self.is_true('metadata'):
            projection = None
        # select which permission filter will be applied to the list of results.
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            # admin_only flag will limit the results to the set on which the user is an admin
            admin_only = self.is_true('admin')
            permchecker = containerauth.list_permission_checker(self, admin_only)
        # if par_cont_name (parent container name) and par_id are not null we return only results
        # within that container
        if par_cont_name:
            if not par_id:
                self.abort(500, 'par_id is required when par_cont_name is provided')
            if self.use_object_id.get(par_cont_name):
                if not bson.ObjectId.is_valid(par_id):
                    self.abort(400, 'not a valid object id')
                par_id = bson.ObjectId(par_id)
            query = {par_cont_name[:-1]: par_id}
        else:
            query = {}
        # this request executes the actual reqeust filtering containers based on the user permissions
        results = permchecker(self.storage.exec_op)('GET', query=query, public=self.public_request, projection=projection)
        if results is None:
            self.abort(404, 'Element not found in container {} {}'.format(storage.cont_name, _id))
        # return only permissions of the current user
        self._filter_all_permissions(results, self.uid, self.user_site)
        # the "count" flag add a count for each container returned
        if self.is_true('counts'):
            self._add_results_counts(results, cont_name)
        # the "measurements" flag applies only to query for sessions
        # and add a list of the measurements in the child acquisitions
        if cont_name == 'sessions' and self.is_true('measurements'):
            self._add_session_measurements(results)
        if self.debug:
            debuginfo.add_debuginfo(self, cont_name, results)
        return results

    def _filter_all_permissions(self, results, uid, site):
        for result in results:
            user_perm = util.user_perm(result.get('permissions', []), uid, site)
            result['permissions'] = [user_perm] if user_perm else []
        return results

    def _add_results_counts(self, results):
        dbc_name = self.config.get('children_cont')
        el_cont_name = cont_name[:-1]
        dbc = config.db.get(dbc_name)
        counts =  dbc.aggregate([
            {'$match': {el_cont_name: {'$in': [res['_id'] for result in results]}}},
            {'$group': {'_id': '$' + el_cont_name, 'count': {"$sum": 1}}}
            ])
        counts = {elem['_id']: elem['count'] for elem in counts}
        for elem in results:
            elem[dbc_name[:-1] + '_count'] = counts.get(elem['_id'], 0)

    def _add_session_measurements(self, results):
        session_measurements = config.db.acquisitions.aggregate([
            {'$match': {'session': {'$in': [sess['_id'] for sess in results]}}},
            {'$group': {'_id': '$session', 'measurements': {'$addToSet': '$measurement'}}}
            ])
        session_measurements = {sess['_id']: sess['measurements'] for sess in session_measurements}
        for sess in results:
            sess['measurements'] = session_measurements.get(sess['_id'], None)

    def get_all_for_user(self, cont_name, uid):
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        projection = self.config['list_projection']
        if self.is_true('metadata'):
            projection = None
        # select which permission filter will be applied to the list of results.
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            self.abort(403, 'this request is not allowed')
        else:
            permchecker = containerauth.list_permission_checker(self)
        query = {}
        user = {
            '_id': uid,
            'site': config.get_item('site', 'id')
        }
        try:
            results = permchecker(self.storage.exec_op)('GET', query=query, user=user, projection=projection)
        except APIStorageException as e:
            self.abort(400, e.message)
        if results is None:
            self.abort(404, 'Element not found in container {} {}'.format(storage.cont_name, _id))
        self._filter_all_permissions(results, uid, user['site'])
        if self.debug:
            debuginfo.add_debuginfo(self, cont_name, results)
        return results

    def post(self, cont_name, **kwargs):
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        log.debug(payload)
        #validate the input payload
        payload_validator(payload, 'POST')
        # Load the parent container in which the new container will be created
        # to check permissions.
        parent_container, parent_id_property = self._get_parent_container(payload)
        # If the new container is a session add the group of the parent project in the payload
        if cont_name == 'sessions':
            payload['group'] = parent_container['group']
        # Always add the id of the parent to the container
        payload[parent_id_property] = parent_container['_id']
        # Optionally inherit permissions of a project from the parent group. The default behaviour
        # for projects is to give admin permissions to the requestor.
        # The default for other containers is to inherit.
        if self.is_true('inherit') and cont_name == 'projects':
            payload['permissions'] = parent_container.get('roles')
        elif cont_name =='projects':
            payload['permissions'] = [{'_id': self.uid, 'access': 'admin', 'site': self.user_site}]
        else:
            payload['permissions'] = parent_container.get('permissions', [])
        # Created and modified timestamps are added here to the payload
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        if payload.get('timestamp'):
            payload['timestamp'] = dateutil.parser.parse(payload['timestamp'])
        permchecker = self._get_permchecker(parent_container=parent_container)
        # This line exec the actual request validating the payload that will create the new container
        # and checking permissions using respectively the two decorators, mongo_validator and permchecker
        result = mongo_validator(permchecker(self.storage.exec_op))('POST', payload=payload)
        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(404, 'Element not added in container {} {}'.format(storage.cont_name, _id))

    def put(self, cont_name, **kwargs):
        _id = kwargs.pop('cid')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container = self._get_container(_id)
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        payload_validator(payload, 'PUT')
        # Check if we are updating the parent container of the element (ie we are moving the container)
        # In this case, we will check permissions on it.
        target_parent_container, parent_id_property = self._get_parent_container(payload)
        if target_parent_container:
            if cont_name in ['sessions', 'acquisitions']:
                payload[parent_id_property] = bson.ObjectId(payload[parent_id_property])
            if cont_name == 'sessions':
                payload['group'] = target_parent_container['group']
            if cont_name == 'projects':
                payload['permissions'] = target_parent_container.get('roles', [])
            else:
                payload['permissions'] = target_parent_container.get('permissions', [])

        payload['modified'] = datetime.datetime.utcnow()
        if payload.get('timestamp'):
            payload['timestamp'] = dateutil.parser.parse(payload['timestamp'])

        permchecker = self._get_permchecker(container, target_parent_container)
        try:
            # This line exec the actual request validating the payload that will update the container
            # and checking permissions using respectively the two decorators, mongo_validator and permchecker
            result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not updated in container {} {}'.format(storage.cont_name, _id))

    def delete(self, cont_name, **kwargs):
        _id = kwargs.pop('cid')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container= self._get_container(_id)
        target_parent_container, parent_id_property = self._get_parent_container(container)
        permchecker = self._get_permchecker(container, target_parent_container)
        try:
            # This line exec the actual delete checking permissions using the decorator permchecker
            result = permchecker(self.storage.exec_op)('DELETE', _id)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.deleted_count == 1:
            if cont_name == 'projects':
                snapshot.remove_private_snapshots_for_project(_id)
                snapshot.remove_permissions_from_snapshots(_id)
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'Element not removed from container {} {}'.format(storage.cont_name, _id))

    def get_groups_with_project(self):
        """
        method to return the list of groups for which there are projects accessible to the user
        """
        group_ids = list(set((p['group'] for p in self.get_all('projects'))))
        return list(config.db.groups.find({'_id': {'$in': group_ids}}, ['name']))


    def _get_validators(self):
        mongo_validator = validators.mongo_from_schema_file(self, self.config.get('storage_schema_file'))
        payload_validator = validators.payload_from_schema_file(self, self.config.get('payload_schema_file'))
        return mongo_validator, payload_validator

    def _get_parent_container(self, payload):
        if not self.config.get('parent_storage'):
            return None, None
        log.debug(payload)
        parent_storage = self.config['parent_storage']
        parent_id_property = parent_storage.cont_name[:-1]
        log.debug(parent_id_property)
        parent_id = payload.get(parent_id_property)
        log.debug(parent_id)
        if parent_id:
            parent_storage.dbc = config.db[parent_storage.cont_name]
            parent_container = parent_storage.get_container(parent_id)
            if parent_container is None:
                self.abort(404, 'Element {} not found in container {}'.format(parent_id, parent_storage.cont_name))
        else:
            parent_container = None
        log.debug(parent_container)
        return parent_container, parent_id_property


    def _get_container(self, _id):
        try:
            container = self.storage.get_container(_id)
        except APIStorageException as e:
            self.abort(400, e.message)
        if container is not None:
            return container
        else:
            self.abort(404, 'Element {} not found in container {}'.format(_id, self.storage.cont_name))

    def _get_permchecker(self, container=None, parent_container=None):
        if self.superuser_request:
            return always_ok
        elif self.public_request:
            return containerauth.public_request(self, container, parent_container)
        else:
            permchecker = self.config['permchecker']
            return permchecker(self, container, parent_container)
