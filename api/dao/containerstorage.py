import bson.errors
import bson.objectid
import pymongo.errors

from .. import util
from .. import config
from ..request import get_current_request
from . import consistencychecker
from . import APIStorageException, APIConflictException
from . import hierarchy

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

    def exec_op(self, action, _id=None, payload=None, query=None, user=None,
                public=False, projection=None, recursive=False, r_payload=None,  # pylint: disable=unused-argument
                replace_metadata=False):
        """
        Generic method to exec an operation.
        The request is dispatched to the corresponding private methods.
        """

        check = consistencychecker.get_container_storage_checker(action, self.cont_name)
        data_op = payload or {'_id': _id}
        check(data_op)
        if action == 'GET' and _id:
            return self._get_el(_id, projection)
        if action == 'GET':
            return self._get_all_el(query, user, projection)
        if action == 'DELETE':
            return self._delete_el(_id)
        if action == 'PUT':
            return self._update_el(_id, payload, recursive, r_payload, replace_metadata)
        if action == 'POST':
            return self._create_el(payload)
        raise ValueError('action should be one of GET, POST, PUT, DELETE')

    def _create_el(self, payload):
        request = get_current_request()
        request.logger.debug(payload)
        try:
            result = self.dbc.insert_one(payload)
        except pymongo.errors.DuplicateKeyError:
            raise APIConflictException('Object with id {} already exists.'.format(payload['_id']))
        return result

    def _update_el(self, _id, payload, recursive=False, r_payload=None, replace_metadata=False):
        replace = None
        if replace_metadata:
            replace = {}
            if payload.get('metadata') is not None:
                replace['metadata'] = util.mongo_sanitize_fields(payload.pop('metadata'))
            if payload.get('subject') is not None and payload['subject'].get('metadata') is not None:
                replace['subject.metadata'] = util.mongo_sanitize_fields(payload['subject'].pop('metadata'))

        update = {
            '$set': util.mongo_dict(payload)
        }
        if replace is not None:
            update['$set'].update(replace)

        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        if recursive and r_payload is not None:
            hierarchy.propagate_changes(self.cont_name, _id, {}, {'$set': util.mongo_dict(r_payload)})
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

    def _get_all_el(self, query, user, projection):
        if user:
            if query.get('permissions'):
                query['$and'] = [{'permissions': {'$elemMatch': user}}, {'permissions': query.pop('permissions')}]
            else:
                query['permissions'] = {'$elemMatch': user}
        request = get_current_request()
        request.logger.debug(query)
        request.logger.debug(projection)
        result = self.dbc.find(query, projection)
        return list(result)


class GroupStorage(ContainerStorage):

    def _create_el(self, payload):
        request = get_current_request()
        request.logger.debug(payload)
        roles = payload.pop('roles')
        return self.dbc.update_one(
            {'_id': payload['_id']},
            {
                '$set': payload,
                '$setOnInsert': {'roles': roles}
            },
            upsert=True)
