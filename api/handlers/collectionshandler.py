import bson
import datetime

from .. import config
from ..auth import containerauth, always_ok
from ..dao import containerstorage, containerutil, noop
from ..web.errors import APIStorageException
from ..validators import verify_payload_exists

from .containerhandler import ContainerHandler

log = config.log


class CollectionsHandler(ContainerHandler):
    # pylint: disable=arguments-differ

    container_handler_configurations = ContainerHandler.container_handler_configurations

    container_handler_configurations['collections'] = {
        'permchecker': containerauth.collection_permissions,
        'storage': containerstorage.ContainerStorage('collections', use_object_id=True, use_delete_tag=True),
        'storage_schema_file': 'collection.json',
        'payload_schema_file': 'collection.json',
        'list_projection': {'info': 0}
    }

    def __init__(self, request=None, response=None):
        super(CollectionsHandler, self).__init__(request, response)
        self.config = self.container_handler_configurations['collections']
        self.storage = self.container_handler_configurations['collections']['storage']

    def get(self, **kwargs):
        return super(CollectionsHandler, self).get('collections', **kwargs)

    def post(self):
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        payload_validator(payload, 'POST')
        payload['permissions'] = [{
            '_id': self.uid,
            'access': 'admin'
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
                sess_ids = [s['_id'] for s in config.db.sessions.find({'project': item_id, 'deleted': {'$exists': False}}, [])]
                acq_ids += [a['_id'] for a in config.db.acquisitions.find({'session': {'$in': sess_ids}, 'deleted': {'$exists': False}}, [])]
            elif item['level'] == 'session':
                acq_ids += [a['_id'] for a in config.db.acquisitions.find({'session': item_id, 'deleted': {'$exists': False}}, [])]
            elif item['level'] == 'acquisition':
                acq_ids += [item_id]
        operator = '$addToSet' if contents['operation'] == 'add' else '$pull'
        if not bson.ObjectId.is_valid(_id):
            self.abort(400, 'not a valid object id')
        config.db.acquisitions.update_many({'_id': {'$in': acq_ids}}, {operator: {'collections': bson.ObjectId(_id)}})


    def delete(self, **kwargs):
        _id = bson.ObjectId(kwargs.pop('cid'))
        self.config = self.container_handler_configurations['collections']
        self.storage = self.config['storage']
        container = self._get_container(_id)
        container['has_children'] = container.get('files') or container.get('analyses')
        permchecker = self._get_permchecker(container, None)
        try:
            # This line exec the actual delete checking permissions using the decorator permchecker
            result = permchecker(self.storage.exec_op)('DELETE', _id)
            config.db.acquisitions.update_many({'collections': _id}, {'$pull': {'collections': _id}})
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.modified_count == 1:
            return {'deleted': 1}
        else:
            self.abort(404, 'Element not removed from container {} {}'.format(self.storage.cont_name, _id))

    def get_all(self):
        projection = self.container_handler_configurations['collections']['list_projection']
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            permchecker = containerauth.list_permission_checker(self)
        query = {}
        results = permchecker(self.storage.exec_op)('GET', query=query, public=self.public_request, projection=projection)
        if not self.superuser_request and not self.is_true('join_avatars'):
            self._filter_all_permissions(results, self.uid)
        if self.is_true('join_avatars'):
            results = ContainerHandler.join_user_info(results)
        for result in results:
            if self.is_true('stats'):
                result = containerutil.get_stats(result, 'collections')
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

        if not self.superuser_request:
            query['permissions._id'] = self.uid

        projection = self.container_handler_configurations['sessions']['list_projection']

        sessions = list(containerstorage.SessionStorage().get_all_el(query, None, projection))

        self._filter_all_permissions(sessions, self.uid)

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

        if not self.superuser_request:
            query['permissions._id'] = self.uid

        projection = self.container_handler_configurations['acquisitions']['list_projection']

        acquisitions = list(containerstorage.AcquisitionStorage().get_all_el(query, None, projection))

        self._filter_all_permissions(acquisitions, self.uid)

        for acquisition in acquisitions:
            acquisition = self.handle_origin(acquisition)
        return acquisitions
