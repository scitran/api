import bson.errors
import bson.objectid

from .. import config
from . import consistencychecker
from . import APIStorageException, APIConflictException

log = config.log


class ListStorage(object):
    """
    This class provides access to sublists of a mongodb collections elements (called containers).
    It is used by ListHandler istances for get, create, update and delete operations on sublist of the containers.
    Examples: permissions in projects, roles in groups, notes in projects, sessions, acquisitions, etc
    """

    def __init__(self, cont_name, list_name, use_object_id = False):
        self.cont_name = cont_name
        self.list_name = list_name
        self.use_object_id = use_object_id
        self.dbc = config.db[cont_name]

    def get_container(self, _id, query_params=None):
        """
        Load a container from the _id.

        This method is usually used to to check permission properties of the container.
        e.g. list of users that can access the container

        For simplicity we load its full content.
        """
        if self.use_object_id:
            _id = bson.objectid.ObjectId(_id)
        query = {'_id': _id}
        projection = None
        if query_params:
            query[self.list_name] = {
                '$elemMatch': query_params
            }
            projection = {self.list_name + '.$': 1, 'permissions': 1, 'public': 1}
        log.debug('query {}'.format(query))
        return self.dbc.find_one(query, projection)

    def exec_op(self, action, _id=None, query_params=None, payload=None, exclude_params=None):
        """
        Generic method to exec an operation.
        The request is dispatched to the corresponding private methods.
        """
        check = consistencychecker.get_list_storage_checker(action, self.list_name)
        check(payload)
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        if action == 'GET':
            return self._get_el(_id, query_params)
        if action == 'DELETE':
            return self._delete_el(_id, query_params)
        if action == 'PUT':
            return self._update_el(_id, query_params, payload, exclude_params)
        if action == 'POST':
            return self._create_el(_id, payload, exclude_params)
        raise ValueError('action should be one of GET, POST, PUT, DELETE')

    def _create_el(self, _id, payload, exclude_params):
        log.debug('payload {}'.format(payload))
        query = {'_id': _id}
        if exclude_params:
            query[self.list_name] = {'$not': {'$elemMatch': exclude_params} }
        update = {'$push': {self.list_name: payload} }
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        result = self.dbc.update_one(query, update)
        if result.matched_count < 1:
            raise APIConflictException('Item already exists in list.')
        return result

    def _update_el(self, _id, query_params, payload, exclude_params):
        log.debug('query_params {}'.format(query_params))
        log.debug('payload {}'.format(payload))
        mod_elem = {}
        for k,v in payload.items():
            mod_elem[self.list_name + '.$.' + k] = v
        query = {'_id': _id }
        if exclude_params is None:
            query[self.list_name] = {'$elemMatch': query_params}
        else:
            query['$and'] = [
                {self.list_name: {'$elemMatch': query_params}},
                {self.list_name: {'$not': {'$elemMatch': exclude_params} }}
            ]
        update = {
            '$set': mod_elem
        }
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        return self.dbc.update_one(query, update)

    def _delete_el(self, _id, query_params):
        log.debug('query_params {}'.format(query_params))
        query = {'_id': _id}
        update = {'$pull': {self.list_name: query_params} }
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        return self.dbc.update_one(query, update)

    def _get_el(self, _id, query_params):
        log.debug('query_params {}'.format(query_params))
        query = {'_id': _id, self.list_name: {'$elemMatch': query_params}}
        projection = {self.list_name + '.$': 1}
        log.debug('query {}'.format(query))
        log.debug('projection {}'.format(projection))
        result = self.dbc.find_one(query, projection)
        if result and result.get(self.list_name):
            return result.get(self.list_name)[0]


class StringListStorage(ListStorage):
    """
    This class provides access to string sublists of a mongodb collections elements (called containers).
    The difference with other sublists is that the elements are not object but strings.
    """

    def get_container(self, _id, query_params=None):
        if self.dbc is None:
            raise RuntimeError('collection not initialized before calling get_container')
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        query = {'_id': _id}
        projection = {self.list_name : 1, 'permissions': 1, 'public': 1, 'roles': 1}
        return self.dbc.find_one(query, projection)

    def exec_op(self, action, _id=None, query_params=None, payload=None, exclude_params=None):
        """
        This method "flattens" the query parameter and the payload to handle string lists
        """
        if query_params is not None:
            query_params = query_params['value']
        if payload is not None:
            payload = payload.get('value')
            if payload is None:
                self.abort(400, 'Key "value" should be defined')
        return super(StringListStorage, self).exec_op(action, _id, query_params, payload, exclude_params)

    def _create_el(self, _id, payload, exclude_params):
        log.debug('payload {}'.format(payload))
        query = {'_id': _id, self.list_name: {'$ne': payload}}
        update = {'$push': {self.list_name: payload}}
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        result = self.dbc.update_one(query, update)
        if result.matched_count < 1:
            raise APIConflictException('Item already exists in list.')
        return result

    def _update_el(self, _id, query_params, payload, exclude_params):
        log.debug('query_params {}'.format(payload))
        log.debug('payload {}'.format(query_params))
        query = {
            '_id': _id,
            '$and':[
                {self.list_name: query_params},
                {self.list_name: {'$ne': payload} }
            ]
        }
        update = {'$set': {self.list_name + '.$': payload}}
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        return self.dbc.update_one(query, update)

    def _get_el(self, _id, query_params):
        log.debug('query_params {}'.format(query_params))
        query = {'_id': _id, self.list_name: query_params}
        projection = {self.list_name + '.$': 1}
        log.debug('query {}'.format(query))
        log.debug('projection {}'.format(projection))
        result = self.dbc.find_one(query, projection)
        if result and result.get(self.list_name):
            return result.get(self.list_name)[0]


class AnalysesStorage(ListStorage):

    def get_fileinfo(self, _id, analysis_id, filename = None):
        _id = bson.ObjectId(_id)
        query = [
            {'$match': {'_id' : _id}},
            {'$unwind': '$' + self.list_name},
            {'$match': {self.list_name+ '._id' : analysis_id}},
            {'$unwind': '$' + self.list_name + '.files'}
        ]
        if filename:
            query.append(
                {'$match': {self.list_name + '.files.name' : filename}}
            )
        log.error(query)
        return [cont['analyses'] for cont in self.dbc.aggregate(query)]

    def add_note(self, _id, analysis_id, payload):
        _id = bson.ObjectId(_id)
        query = {
            '_id': _id,
            'analyses._id': analysis_id
        }
        update = {
            '$push': {
                'analyses.$.notes': payload
            }
        }
        return self.dbc.update_one(query, update)

    def delete_note(self, _id, analysis_id, note_id):
        _id = bson.ObjectId(_id)
        query = {
            '_id': _id,
            'analyses._id': analysis_id
        }
        update = {
            '$pull': {
                'analyses.$.notes': {
                    '_id': note_id
                }
            }
        }
        return self.dbc.update_one(query, update)
