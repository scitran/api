import bson.errors
import bson.objectid

from .. import util
from .. import config
from . import APIStorageException

log = config.log


class ContainerStorage(object):
    """
    This class provides access to mongodb collection elements (called containers).
    It is used by ContainerHandler istances for get, create, update and delete operations on containers.
    Examples: projects, sessions, acquisitions and collections
    """

    def __init__(self, cont_name, use_object_id = False):
        self.cont_name = cont_name
        self.use_object_id = use_object_id
        self.dbc = config.db[cont_name]

    def get_container(self, _id):
        return self._get_el(_id)

    def exec_op(self, action, _id=None, payload=None, query=None, user=None, public=False, projection=None):
        """
        Generic method to exec an operation.
        The request is dispatched to the corresponding private methods.
        """

        if action == 'GET' and _id:
            return self._get_el(_id, projection)
        if action == 'GET':
            return self._get_all_el(query, user, public, projection)
        if action == 'DELETE':
            return self._delete_el(_id)
        if action == 'PUT':
            return self._update_el(_id, payload)
        if action == 'POST':
            return self._create_el(payload)
        raise ValueError('action should be one of GET, POST, PUT, DELETE')

    def _create_el(self, payload):
        log.debug(payload)
        if payload['_id']:
            payload['_id'] = bson.objectid.ObjectId(str(payload['_id']))
        return self.dbc.insert_one(payload)

    def _update_el(self, _id, payload):
        update = {
            '$set': util.mongo_dict(payload)
        }
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        return self.dbc.update_one({'_id': _id}, update)

    def _delete_el(self, _id):
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        return self.dbc.delete_one({'_id':_id})

    def _get_el(self, _id, projection=None):
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        return self.dbc.find_one(_id, projection)

    def _get_all_el(self, query, user, public, projection):
        if user:
            if query.get('permissions'):
                query['$and'] = [{'permissions': {'$elemMatch': user}}, {'permissions': query.pop('permissions')}]
            else:
                query['permissions'] = {'$elemMatch': user}
        log.debug(query)
        log.debug(projection)
        result = self.dbc.find(query, projection)
        return list(result)

