import bson
import datetime
import dateutil

from .. import base
from .. import util
from .. import config
from .. import debuginfo
from .. import validators
from ..auth import containerauth, always_ok
from ..dao import APIStorageException, containerstorage, containerutil, noop, hierarchy
from ..dao.liststorage import AnalysesStorage
from ..types import Origin
from ..jobs.queue import Queue
from ..jobs.jobs import Job

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
            'propagated_properties': ['archived', 'public'],
            'children_cont': 'sessions'
        },
        'sessions': {
            'storage': containerstorage.ContainerStorage('sessions', use_object_id=use_object_id['sessions']),
            'permchecker': containerauth.default_container,
            'parent_storage': containerstorage.ContainerStorage('projects', use_object_id=use_object_id['projects']),
            'storage_schema_file': 'session.json',
            'payload_schema_file': 'session.json',
            'list_projection': {'metadata': 0},
            'propagated_properties': ['archived'],
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
        self.storage = None
        self.config = None

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
            self.abort(404, 'Element not found in container {} {}'.format(self.storage.cont_name, _id))
        if not self.superuser_request:
            self._filter_permissions(result, self.uid, self.user_site)
        # build and insert file paths if they are requested
        if self.is_true('paths'):
            for fileinfo in result['files']:
                fileinfo['path'] = util.path_from_hash(fileinfo['hash'])
        if self.debug:
            debuginfo.add_debuginfo(self, cont_name, result)

        if cont_name == 'sessions':
            result = self.handle_analyses(result)

        return self.handle_origin(result)

    def handle_origin(self, result):
        """
        Given an object with a `files` array key, coalesce and merge file origins if requested.
        """

        # If `join=origin` passed as a request param, join out that key
        join_origin = 'origin' in self.request.params.getall('join')

        # If it was requested, create a map of each type of origin to hold the join
        if join_origin:
            result['join-origin'] = {
                Origin.user.name:   {},
                Origin.device.name: {},
                Origin.job.name:    {}
            }

        for f in result.get('files', []):
            origin = f.get('origin', None)

            if origin is None:
                # Backfill origin maps if none provided from DB
                f['origin'] = {
                    'type': str(Origin.unknown),
                    'id': None
                }

            elif join_origin:
                j_type = f['origin']['type']
                j_id   = f['origin']['id']
                j_id_b = j_id

                # Some tables don't use BSON for their primary keys.
                if j_type not in (Origin.user, Origin.device):
                    j_id_b = bson.ObjectId(j_id)

                # Join from database if we haven't for this origin before
                if j_type != 'unknown' and result['join-origin'][j_type].get(j_id, None) is None:
                    result['join-origin'][j_type][j_id] = config.db[j_type + 's'].find_one({'_id': j_id_b})

        return result

    def handle_analyses(self, result):
        """
        Given an object with an `analyses` array key, inflate job info for job-based analyses
        """
        analyses = result.get('analyses')
        if analyses is None:
            return result
        for a in analyses:
            if a.get('job') is not None:
                a = AnalysesStorage.inflate_job_info(a)

        result['analyses'] = analyses
        return result

    def _filter_permissions(self, result, uid, site):
        """
        if the user is not admin only her permissions are returned.
        """
        user_perm = util.user_perm(result.get('permissions', []), uid, site)
        if user_perm.get('access') != 'admin':
            result['permissions'] = [user_perm] if user_perm else []

    def get_jobs(self, cont_name, cid):
        """
        .. http:get:: /api/(cont_name)/(cid)/jobs

            Return any jobs that mention this container as an input.

            :query states: filter results by job state
            :type states: string

            :query tags: filter results by job tags
            :type cid: string

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                GET /api/sessions/3/jobs?states=pending&states=failed&tags=a&tags=b HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                [
                    {
                        "_id": "57336257ea360500272c2f11",
                        "algorithm_id": "dicom_mr_classifier",
                        "state": "pending",
                        "tags": [
                            "a"
                        ]
                        //...
                    },
                    {
                        "_id": "57336257ea360500272c2f12",
                        "algorithm_id": "dcm_convert",
                        "state": "failed",
                        "tags": [
                            "b"
                        ]
                       // ...
                    }
                ]
        """

        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        if cont_name != 'sessions':
            self.abort(400, 'Can only request jobs at the session level.')

        c = self._get_container(cid)
        permchecker = self._get_permchecker(c)
        permchecker(noop)('GET', cid)

        children = hierarchy.get_children('session', cid)
        id_array = [str(c['_id']) for c in children]
        cont_array = [containerutil.ContainerReference('acquisition', cid) for cid in id_array]

        states = self.request.GET.getall('states')
        tags   = self.request.GET.getall('tags')
        jobs = Queue.search(cont_array, states=states, tags=tags)

        response = {}
        for j in jobs:
            job  = Job.load(j)
            for _,v in job.inputs.iteritems():
                if v.type == 'acquisition' and v.id in id_array:
                    if response.get(v.id) is not None:
                        response[v.id].append(job)
                    else:
                        response[v.id] = [job]
        return response

    def get_all(self, cont_name, par_cont_name=None, par_id=None):
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']

        projection = self.config['list_projection']
        if self.is_true('metadata'):
            projection.pop('metadata')
            if not projection:
                projection = None

        # select which permission filter will be applied to the list of results.
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            permchecker = containerauth.list_permission_checker(self)
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
        if not self.is_true('archived'):
            query['archived'] = {'$ne': True}
        # this request executes the actual reqeust filtering containers based on the user permissions
        results = permchecker(self.storage.exec_op)('GET', query=query, public=self.public_request, projection=projection)
        if results is None:
            self.abort(404, 'No elements found in container {}'.format(self.storage.cont_name))
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

        for result in results:
            result = self.handle_origin(result)
            if cont_name == 'sessions':
                result = self.handle_analyses(result)

        return results

    def _filter_all_permissions(self, results, uid, site):
        for result in results:
            user_perm = util.user_perm(result.get('permissions', []), uid, site)
            result['permissions'] = [user_perm] if user_perm else []
        return results

    def _add_results_counts(self, results, cont_name):
        dbc_name = self.config.get('children_cont')
        el_cont_name = cont_name[:-1]
        dbc = config.db.get(dbc_name)
        counts =  dbc.aggregate([
            {'$match': {el_cont_name: {'$in': [res['_id'] for res in results]}}},
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
            self.abort(404, 'Element not found in container {} {}'.format(self.storage.cont_name, uid))
        self._filter_all_permissions(results, uid, user['site'])
        if self.debug:
            debuginfo.add_debuginfo(self, cont_name, results)
        return results

    def post(self, cont_name):
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        self.request.logger.debug(payload)
        #validate the input payload
        payload_validator(payload, 'POST')
        # Load the parent container in which the new container will be created
        # to check permissions.
        parent_container, parent_id_property = self._get_parent_container(payload)
        # Always add the id of the parent to the container
        payload[parent_id_property] = parent_container['_id']
        # If the new container is a session add the group of the parent project in the payload
        if cont_name == 'sessions':
            payload['group'] = parent_container['group']
            payload['subject'] = containerutil.add_id_to_subject(payload.get('subject'), payload.get('project'))
        # Optionally inherit permissions of a project from the parent group. The default behaviour
        # for projects is to give admin permissions to the requestor.
        # The default for other containers is to inherit.
        if self.is_true('inherit') and cont_name == 'projects':
            payload['permissions'] = parent_container.get('roles')
        elif cont_name =='projects':
            payload['permissions'] = [{'_id': self.uid, 'access': 'admin', 'site': self.user_site}] if self.uid else []
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
            self.abort(404, 'Element not added in container {}'.format(self.storage.cont_name))

    def put(self, cont_name, **kwargs):
        _id = kwargs.pop('cid')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container = self._get_container(_id)
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        payload_validator(payload, 'PUT')

        # Check if any payload keys are any propogated property, add to r_payload
        rec = False
        r_payload = {}
        prop_keys = set(payload.keys()).intersection(set(self.config.get('propagated_properties', [])))
        if prop_keys:
            rec = True
            for key in prop_keys:
                r_payload[key] = payload[key]

        # Check if we are updating the parent container of the element (ie we are moving the container)
        # In this case, we will check permissions on it.
        target_parent_container, parent_id_property = self._get_parent_container(payload)
        if target_parent_container:
            if cont_name in ['sessions', 'acquisitions']:
                payload[parent_id_property] = bson.ObjectId(payload[parent_id_property])
                parent_perms = target_parent_container.get('permissions', [])
                payload['permissions'] = parent_perms

            if cont_name == 'sessions':
                payload['group'] = target_parent_container['group']
                # Propagate permissions down to acquisitions
                rec = True
                r_payload['permissions'] = parent_perms


        payload['modified'] = datetime.datetime.utcnow()
        if payload.get('timestamp'):
            payload['timestamp'] = dateutil.parser.parse(payload['timestamp'])
        if cont_name == 'sessions':
            if payload.get('subject') is not None and payload['subject'].get('_id') is not None:
                # Ensure subject id is a bson object
                payload['subject']['_id'] = bson.ObjectId(str(payload['subject']['_id']))
        permchecker = self._get_permchecker(container, target_parent_container)

        # Specifies wether the metadata fields should be replaced or patched with payload value
        replace_metadata = self.get_param('replace_metadata', default=False)
        try:
            # This line exec the actual request validating the payload that will update the container
            # and checking permissions using respectively the two decorators, mongo_validator and permchecker
            result = mongo_validator(permchecker(self.storage.exec_op))('PUT',
                        _id=_id, payload=payload, recursive=rec, r_payload=r_payload, replace_metadata=replace_metadata)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not updated in container {} {}'.format(self.storage.cont_name, _id))

    def delete(self, cont_name, **kwargs):
        _id = kwargs.pop('cid')
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        container= self._get_container(_id)
        target_parent_container, _ = self._get_parent_container(container)
        permchecker = self._get_permchecker(container, target_parent_container)
        try:
            # This line exec the actual delete checking permissions using the decorator permchecker
            result = permchecker(self.storage.exec_op)('DELETE', _id)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'Element not removed from container {} {}'.format(self.storage.cont_name, _id))

    def get_groups_with_project(self):
        """
        method to return the list of groups for which there are projects accessible to the user
        """
        group_ids = list(set((p['group'] for p in self.get_all('projects'))))
        return list(config.db.groups.find({'_id': {'$in': group_ids}}, ['name']))

    def _get_validators(self):
        mongo_schema_uri = validators.schema_uri('mongo', self.config.get('storage_schema_file'))
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', self.config.get('payload_schema_file'))
        payload_validator = validators.from_schema_path(payload_schema_uri)
        return mongo_validator, payload_validator

    def _get_parent_container(self, payload):
        if not self.config.get('parent_storage'):
            return None, None
        parent_storage = self.config['parent_storage']
        parent_id_property = parent_storage.cont_name[:-1]
        parent_id = payload.get(parent_id_property)
        if parent_id:
            parent_storage.dbc = config.db[parent_storage.cont_name]
            parent_container = parent_storage.get_container(parent_id)
            if parent_container is None:
                self.abort(404, 'Element {} not found in container {}'.format(parent_id, parent_storage.cont_name))
        else:
            parent_container = None
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
            return containerauth.public_request(self, container)
        else:
            permchecker = self.config['permchecker']
            return permchecker(self, container, parent_container)
