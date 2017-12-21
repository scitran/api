import bson
import datetime

from .. import config
from ..auth import containerauth, always_ok
from ..dao import containerstorage, containerutil, noop
from ..web.errors import APIStorageException
from ..validators import verify_payload_exists
from ..web.request import AccessType

from .containerhandler import ContainerHandler
from .projectsettings import get_phi_fields

log = config.log


class CollectionsHandler(ContainerHandler):
    # pylint: disable=arguments-differ

    container_handler_configurations = ContainerHandler.container_handler_configurations

    container_handler_configurations['collections'] = {
        'permchecker': containerauth.collection_permissions,
        'storage': containerstorage.ContainerStorage('collections', use_object_id=True),
        'storage_schema_file': 'collection.json',
        'payload_schema_file': 'collection.json',
        'list_projection': {'info': 0}
    }

    def __init__(self, request=None, response=None):
        super(CollectionsHandler, self).__init__(request, response)
        self.config = self.container_handler_configurations['collections']
        self.storage = self.container_handler_configurations['collections']['storage']

    def get(self, **kwargs):
        log.debug(kwargs)
        return super(CollectionsHandler, self).get(cont_name='collections', **kwargs)

    def post(self):
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        payload_validator(payload, 'POST')
        payload['permissions'] = [{
            '_id': self.uid,
            'access': 'admin',
            'phi-access': True
        }]
        payload['curator'] = self.uid
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        result = mongo_validator(self.storage.exec_op)('POST', payload=payload)

        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(404, 'Element not added in collection {}'.format(self.uid))

    @verify_payload_exists
    def put(self, **kwargs):
        _id = kwargs.pop('cid')
        container = self._get_container(_id)
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body or {}
        if not payload:
            self.abort(400, 'PUT request body cannot be empty')
        contents = payload.pop('contents', None)
        payload_validator(payload, 'PUT')
        permchecker = self._get_permchecker(container=container)
        payload['modified'] = datetime.datetime.utcnow()
        try:
            result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.modified_count == 1:
            self._add_contents(contents, _id)
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not updated in collection {} {}'.format(self.storage.cont_name, _id))

    def _add_contents(self, contents, _id):
        if not contents:
            return
        acq_ids = []
        for item in contents['nodes']:
            if not bson.ObjectId.is_valid(item.get('_id')):
                self.abort(400, 'not a valid object id')
            item_id = bson.ObjectId(item['_id'])
            if item['level'] == 'project':
                sess_ids = [s['_id'] for s in config.db.sessions.find({'project': item_id}, [])]
                acq_ids += [a['_id'] for a in config.db.acquisitions.find({'session': {'$in': sess_ids}}, [])]
            elif item['level'] == 'session':
                acq_ids += [a['_id'] for a in config.db.acquisitions.find({'session': item_id}, [])]
            elif item['level'] == 'acquisition':
                acq_ids += [item_id]
        operator = '$addToSet' if contents['operation'] == 'add' else '$pull'
        if not bson.ObjectId.is_valid(_id):
            self.abort(400, 'not a valid object id')
        config.db.acquisitions.update_many({'_id': {'$in': acq_ids}}, {operator: {'collections': bson.ObjectId(_id)}})

    def delete(self, **kwargs):
        _id = kwargs.get('cid')
        super(CollectionsHandler, self).delete('collections', **kwargs)
        config.db.acquisitions.update_many({'collections': bson.ObjectId(_id)}, {'$pull': {'collections': bson.ObjectId(_id)}})

    def get_all(self):
        projection = None
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            permchecker = containerauth.list_permission_checker(self)
        query = {}
        if self.is_true('phi'):
            projection = None
            phi = True
        else:
            phi = False
            projection = {'info': 0, 'tags': 0, 'files.info':0}
        results = permchecker(self.storage.exec_op)('GET', query=query, public=self.public_request, projection=projection, phi=phi)
        log.debug(results)
        if not self.superuser_request and not self.is_true('join_avatars'):
            self._filter_all_permissions(results, self.uid)
        if self.is_true('join_avatars'):
            results = ContainerHandler.join_user_info(results)
        for result in results:
            if self.is_true('stats'):
                result = containerutil.get_stats(result, 'collections')
            if phi:
                self.log_user_access(AccessType.view_container, cont_name='collections', cont_id=result.get('_id'))
        return results

    def curators(self):
        curator_ids = []
        for collection in self.get_all():
            if collection['curator'] not in curator_ids:
                curator_ids.append(collection['curator'])
        curators = config.db.users.find(
            {'_id': {'$in': curator_ids}},
            ['firstname', 'lastname']
            )
        return list(curators)

    def get_sessions(self, cid):
        """Return the list of sessions in a collection."""

        # Confirm user has access to collection
        container = self._get_container(cid)
        permchecker = self._get_permchecker(container=container)
        permchecker(noop)('GET', _id=cid)

        # Find list of relevant sessions
        agg_res = config.db.acquisitions.aggregate([
                {'$match': {'collections': bson.ObjectId(cid)}},
                {'$group': {'_id': '$session'}},
                ])
        query = {'_id': {'$in': [ar['_id'] for ar in agg_res]}}


        if not self.is_true('archived'):
            query['archived'] = {'$ne': True}

        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            permchecker = containerauth.list_permission_checker(self)
        projection = get_phi_fields("sessions", "site")
        if self.is_true('phi'):
            projection = None
            phi = True
        else:
            phi = False

        sessions = permchecker(containerstorage.SessionStorage().exec_op)('GET', query=query, public=self.public_request, projection=projection, phi=phi)
        self._filter_all_permissions(sessions, self.uid)
        if self.is_true('measurements'):
            self._add_session_measurements(sessions)
        for sess in sessions:
            sess = self.handle_origin(sess)
        return sessions

    def get_acquisitions(self, cid):
        """Return the list of acquisitions in a collection."""

        # Confirm user has access to collection
        container = self._get_container(cid)
        permchecker = self._get_permchecker(container=container)
        permchecker(noop)('GET', _id=cid)


        query = {'collections': bson.ObjectId(cid)}
        sid = self.get_param('session', '')
        if bson.ObjectId.is_valid(sid):
            query['session'] = bson.ObjectId(sid)
        elif sid != '':
            self.abort(400, sid + ' is not a valid ObjectId')

        if not self.is_true('archived'):
            query['archived'] = {'$ne': True}

        if not self.superuser_request:
            query['permissions._id'] = self.uid
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            permchecker = containerauth.list_permission_checker(self)
        projection = get_phi_fields("acquisitions", "site")
        if self.is_true('phi'):
            projection = None
            phi = True
        else:
            phi = False

        acquisitions = permchecker(containerstorage.AcquisitionStorage().exec_op)('GET', query=query, public=self.public_request, projection=projection, phi=phi)
        self._filter_all_permissions(acquisitions, self.uid)

        for acquisition in acquisitions:
            acquisition = self.handle_origin(acquisition)
        return acquisitions
