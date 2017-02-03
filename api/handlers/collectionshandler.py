import datetime

from .. import util
from .. import config
from ..auth import containerauth, always_ok
from ..dao import containerstorage
from ..dao import APIStorageException

from containerhandler import ContainerHandler

log = config.log


class CollectionsHandler(ContainerHandler):

    container_handler_configurations = ContainerHandler.container_handler_configurations

    container_handler_configurations['collections'] = {
        'permchecker': containerauth.collection_permissions,
        'storage': containerstorage.ContainerStorage('collections', use_object_id=True),
        'storage_schema_file': 'collection.json',
        'payload_schema_file': 'collection.json',
        'list_projection': {'metadata': 0}
    }

    def post(self, **kwargs):
        self.config = self.container_handler_configurations['collections']
        self.storage = self.config['storage']
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body
        log.debug(payload)
        payload_validator(payload, 'POST')
        payload['permissions'] = [{
            '_id': self.uid,
            'site': self.user_site,
            'access': 'admin'
        }]
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        result = mongo_validator(self.storage.exec_op)('POST', payload=payload)

        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(404, 'Element not added in collection {}'.format(_id))

    def put(self, **kwargs):
        _id = kwargs.pop('cid')
        self.config = self.container_handler_configurations['collections']
        self.storage = self.config['storage']
        container = self._get_container(_id)
        mongo_validator, payload_validator = self._get_validators()

        payload = self.request.json_body or {}
        contents = payload.pop('contents', None)
        payload_validator(payload, 'PUT')
        permchecker = self._get_permchecker(container)
        payload['modified'] = str(datetime.datetime.utcnow())
        try:
            result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result.modified_count == 1:
            self._add_contents(contents, _id)
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not updated in collection {} {}'.format(storage.cont_name, _id))

    def _add_contents(self, contents, _id):
        if not contents:
            return
        acq_ids = []
        for item in contents['nodes']:
            if not util.ObjectId.is_valid(item.get('_id')):
                self.abort(400, 'not a valid object id')
            item_id = util.ObjectId(item['_id'])
            if item['level'] == 'project':
                sess_ids = [s['_id'] for s in config.db.sessions.find({'project': item_id}, [])]
                acq_ids += [a['_id'] for a in config.db.acquisitions.find({'session': {'$in': sess_ids}}, [])]
            elif item['level'] == 'session':
                acq_ids += [a['_id'] for a in config.db.acquisitions.find({'session': item_id}, [])]
            elif item['level'] == 'acquisition':
                acq_ids += [item_id]
        operator = '$addToSet' if contents['operation'] == 'add' else '$pull'
        log.info(' '.join(['collection', _id, operator, str(acq_ids)]))
        if not util.ObjectId.is_valid(_id):
            self.abort(400, 'not a valid object id')
        config.db.acquisitions.update_many({'_id': {'$in': acq_ids}}, {operator: {'collections': util.ObjectId(_id)}})

    def delete(self, cont_name, **kwargs):
        _id = kwargs.get('cid')
        super(CollectionsHandler, self).delete(cont_name, **kwargs)
        config.db.acquisitions.update_many({'collections': util.ObjectId(_id)}, {'$pull': {'collections': util.ObjectId(_id)}})

    def get_all(self, cont_name):
        self.config = self.container_handler_configurations[cont_name]
        self.storage = self.config['storage']
        projection = self.config['list_projection']
        if self.is_true('metadata'):
            projection = None
        if self.superuser_request:
            permchecker = always_ok
        elif self.public_request:
            permchecker = containerauth.list_public_request
        else:
            admin_only = self.is_true('admin')
            permchecker = containerauth.list_permission_checker(self, admin_only)
        query = {}
        results = permchecker(self.storage.exec_op)('GET', query=query, public=self.public_request, projection=projection)
        if results is None:
            self.abort(404, 'Element not found in collection {} {}'.format(storage.cont_name, _id))
        self._filter_all_permissions(results, self.uid, self.user_site)
        if self.is_true('counts'):
            self._add_results_counts(results)
        if self.debug:
            for coll in results:
                coll['debug'] = {}
                cid = str(coll['_id'])
                coll['debug']['details'] =  self.uri_for('coll_details', cont_name='collections', cid=cid, _full=True) + '?user=' + self.get_param('user', '')
                coll['debug']['acquisitions'] = self.uri_for('coll_acq', cont_name='collections', cid=cid, _full=True) + '?user=' + self.get_param('user', '')
                coll['debug']['sessions'] =     self.uri_for('coll_ses', cont_name='collections', cid=cid, _full=True) + '?user=' + self.get_param('user', '')
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
        curator_ids = list(set((c['curator'] for c in self.get_all('collections'))))
        return list(config.db.users.find({'_id': {'$in': curator_ids}}, ['firstname', 'lastname']))

    def get_sessions(self, cont_name, cid):
        """Return the list of sessions in a collection."""

        # FIXME use storage and permission checking abstractions
        self.config = self.container_handler_configurations['collections']
        self.storage = self.config['storage']
        if not util.ObjectId.is_valid(cid):
            self.abort(400, 'not a valid object id')
        _id = util.ObjectId(cid)
        if not self.storage.dbc.find_one({'_id': _id}):
            self.abort(404, 'no such Collection')
        agg_res = config.db.acquisitions.aggregate([
                {'$match': {'collections': _id}},
                {'$group': {'_id': '$session'}},
                ])
        query = {'_id': {'$in': [ar['_id'] for ar in agg_res]}}
        projection = self.container_handler_configurations['sessions']['list_projection']
        if self.is_true('metadata'):
            projection = None
        log.debug(query)
        log.debug(projection)
        sessions = list(config.db.sessions.find(query, projection))
        self._filter_all_permissions(sessions, self.uid, self.user_site)
        if self.is_true('measurements'):
            self._add_session_measurements(sessions)
        if self.debug:
            for sess in sessions:
                sess['debug'] = {}
                sid = str(sess['_id'])
                sess['debug']['details'] = self.uri_for('cont_details', cont_name='sessions', cid=sid, _full=True) + '?user=' + self.get_param('user', '')
                sess['debug']['acquisitions'] = self.uri_for('coll_acq', cont_name='collections', cid=cid, _full=True) + '?session=%s&user=%s' % (sid, self.get_param('user', ''))
        return sessions

    def get_acquisitions(self, cid, **kwargs):
        """Return the list of acquisitions in a collection."""

        # FIXME use storage and permission checking abstractions
        self.config = self.container_handler_configurations['collections']
        self.storage = self.config['storage']
        if not util.ObjectId.is_valid(cid):
            self.abort(400, 'not a valid object id')
        _id = util.ObjectId(cid)
        if not self.storage.dbc.find_one({'_id': _id}):
            self.abort(404, 'no such Collection')
        query = {'collections': _id}
        sid = self.get_param('session', '')
        if util.ObjectId.is_valid(sid):
            query['session'] = util.ObjectId(sid)
        elif sid != '':
            self.abort(400, sid + ' is not a valid ObjectId')
        projection = self.container_handler_configurations['acquisitions']['list_projection']
        if self.is_true('metadata'):
            projection = None
        acquisitions = list(config.db.acquisitions.find(query, projection))
        self._filter_all_permissions(acquisitions, self.uid, self.user_site)
        for acq in acquisitions:
            acq.setdefault('timestamp', datetime.datetime.utcnow())
        if self.debug:
            for acq in acquisitions:
                acq['debug'] = {}
                aid = str(acq['_id'])
                acq['debug']['details'] = self.uri_for('cont_details', cont_name='acquisitions', cid=aid, _full=True) + '?user=' + self.get_param('user', '')
        return acquisitions


