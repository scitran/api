import bson
import datetime

from .. import config
from ..auth import containerauth, always_ok
from ..dao import containerstorage
from ..dao import APIStorageException

from .containerhandler import ContainerHandler

log = config.log


class CollectionsHandler(ContainerHandler):
    # pylint: disable=arguments-differ

    container_handler_configurations = ContainerHandler.container_handler_configurations

    container_handler_configurations['collections'] = {
        'permchecker': containerauth.collection_permissions,
        'storage': containerstorage.ContainerStorage('collections', use_object_id=True),
        'storage_schema_file': 'collection.json',
        'payload_schema_file': 'collection.json',
        'list_projection': {'metadata': 0}
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
        log.debug(payload)
        payload_validator(payload, 'POST')
        payload['permissions'] = [{
            '_id': self.uid,
            'site': self.user_site,
            'access': 'admin'
        }]
        payload['curator'] = self.uid
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        result = mongo_validator(self.storage.exec_op)('POST', payload=payload)

        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(404, 'Element not added in collection {}'.format(self.uid))

    def put(self, **kwargs):
        _id = kwargs.pop('cid')
        container = self._get_container(_id)
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body or {}
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
        log.info(' '.join(['collection', _id, operator, str(acq_ids)]))
        if not bson.ObjectId.is_valid(_id):
            self.abort(400, 'not a valid object id')
        config.db.acquisitions.update_many({'_id': {'$in': acq_ids}}, {operator: {'collections': bson.ObjectId(_id)}})

    def delete(self, **kwargs):
        _id = kwargs.get('cid')
        super(CollectionsHandler, self).delete('collections', **kwargs)
        config.db.acquisitions.update_many({'collections': bson.ObjectId(_id)}, {'$pull': {'collections': bson.ObjectId(_id)}})

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
        if results is None:
            self.abort(404, 'Element not found in collection {}'.format(self.storage.cont_name))
        self._filter_all_permissions(results, self.uid, self.user_site)
        if self.is_true('counts'):
            self._add_results_counts(results)
        return results

    def _add_results_counts(self, results):
        session_counts = config.db.acquisitions.aggregate([
            {'$match': {'collections': {'$in': [collection['_id'] for collection in results]}}},
            {'$unwind': "$collections"},
            {'$group': {'_id': "$collections", 'sessions': {'$addToSet': "$session"}}}
            ])
        session_counts = {coll['_id']: len(coll['sessions']) for coll in session_counts}
        for coll in results:
            coll['session_count'] = session_counts.get(coll['_id'], 0)

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
        if not bson.ObjectId.is_valid(cid):
            self.abort(400, 'not a valid object id')
        _id = bson.ObjectId(cid)
        if not self.storage.dbc.find_one({'_id': _id}):
            self.abort(404, 'no such Collection')
        agg_res = config.db.acquisitions.aggregate([
                {'$match': {'collections': _id}},
                {'$group': {'_id': '$session'}},
                ])
        query = {'_id': {'$in': [ar['_id'] for ar in agg_res]}}
        projection = self.container_handler_configurations['sessions']['list_projection']
        log.debug(query)
        log.debug(projection)
        sessions = list(config.db.sessions.find(query, projection))
        self._filter_all_permissions(sessions, self.uid, self.user_site)
        if self.is_true('measurements'):
            self._add_session_measurements(sessions)
        for sess in sessions:
            sess = self.handle_origin(sess)
        return sessions

    def get_acquisitions(self, cid):
        """Return the list of acquisitions in a collection."""
        if not bson.ObjectId.is_valid(cid):
            self.abort(400, 'not a valid object id')
        _id = bson.ObjectId(cid)
        if not self.storage.dbc.find_one({'_id': _id}):
            self.abort(404, 'no such Collection')
        query = {'collections': _id}
        sid = self.get_param('session', '')
        if bson.ObjectId.is_valid(sid):
            query['session'] = bson.ObjectId(sid)
        elif sid != '':
            self.abort(400, sid + ' is not a valid ObjectId')
        projection = self.container_handler_configurations['acquisitions']['list_projection']
        acquisitions = list(config.db.acquisitions.find(query, projection))
        self._filter_all_permissions(acquisitions, self.uid, self.user_site)
        for acq in acquisitions:
            acq.setdefault('timestamp', datetime.datetime.utcnow())
        for acquisition in acquisitions:
            acquisition = self.handle_origin(acquisition)
        return acquisitions
