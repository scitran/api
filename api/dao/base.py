import bson
import pymongo.errors

from . import APIStorageException, APIConflictException, APINotFoundException
from . import consistencychecker
from . import containerutil
from . import hierarchy
from .. import config
from .. import util


log = config.log

# TODO: Find a better place to put this until OOP where we can just call cont.children
CHILD_MAP = {
    'groups':   'projects',
    'projects': 'sessions',
    'sessions': 'acquisitions'
}

PARENT_MAP = {v: k for k,v in CHILD_MAP.iteritems()}

# All "containers" are required to return these fields
# 'All' includes users
BASE_DEFAULTS = {
    '_id':      None,
    'created':  None,
    'modified': None
}

# All containers that inherit from 'container' in the DM
CONTAINER_DEFAULTS = {
    'permissions':  [],
    'files':        [],
    'notes':        [],
    'tags':         [],
    'info':         {}
}


class ContainerStorage(object):
    """
    This class provides access to mongodb collection elements (called containers).
    It is used by ContainerHandler istances for get, create, update and delete operations on containers.
    Examples: projects, sessions, acquisitions and collections
    """

    def __init__(self, cont_name, use_object_id=False):
        self.cont_name = cont_name
        self.use_object_id = use_object_id
        self.dbc = config.db[cont_name]

    @classmethod
    def factory(cls, cont_name):
        """
        Factory method to aid in the creation of a ContainerStorage instance
        when cont_name is dynamic.
        """
        cont_storage_name = containerutil.singularize(cont_name).capitalize() + 'Storage'
        for subclass in cls.__subclasses__():
            if subclass.__name__ == cont_storage_name:
                return subclass()
        return cls(containerutil.pluralize(cont_name)) # cover 100

    def _fill_default_values(self, cont):
        if cont:
            defaults = BASE_DEFAULTS.copy()
            if self.cont_name not in ['groups', 'users']:
                defaults.update(CONTAINER_DEFAULTS)
            defaults.update(cont)
            cont = defaults
        return cont

    def get_container(self, _id, projection=None, get_children=False):
        cont = self.get_el(_id, projection=projection)
        if cont is None:
            raise APINotFoundException('Could not find {} {}'.format(self.cont_name, _id))
        if get_children:
            children = self.get_children(_id, projection=projection)
            cont[CHILD_MAP[self.cont_name]] = children
        return cont

    def get_children(self, _id, projection=None, uid=None):
        try:
            child_name = CHILD_MAP[self.cont_name]
        except KeyError: # cover 100
            raise APINotFoundException('Children cannot be listed from the {0} level'.format(self.cont_name))
        if not self.use_object_id:
            query = {containerutil.singularize(self.cont_name): _id}
        else:
            query = {containerutil.singularize(self.cont_name): bson.ObjectId(_id)}
        
        if uid:
            query['permissions'] = {'$elemMatch': {'_id': uid}}
        if not projection:
            projection = {'info': 0, 'files.info': 0, 'subject': 0, 'tags': 0}
        return ContainerStorage.factory(child_name).get_all_el(query, None, projection)

    def _from_mongo(self, cont):
        return cont

    def _to_mongo(self, payload):
        return payload

    def exec_op(self, action, _id=None, payload=None, query=None, user=None,
                public=False, projection=None, recursive=False, r_payload=None,  # pylint: disable=unused-argument
                replace_metadata=False, unset_payload=None):
        """
        Generic method to exec a CRUD operation from a REST verb.
        """

        check = consistencychecker.get_container_storage_checker(action, self.cont_name)
        data_op = payload or {'_id': _id}
        check(data_op)
        if action == 'GET' and _id:
            return self.get_el(_id, projection=projection, fill_defaults=True)
        if action == 'GET':
            return self.get_all_el(query, user, projection, fill_defaults=True)
        if action == 'DELETE':
            return self.delete_el(_id)
        if action == 'PUT':
            return self.update_el(_id, payload, unset_payload=unset_payload, recursive=recursive, r_payload=r_payload, replace_metadata=replace_metadata)
        if action == 'POST':
            return self.create_el(payload)
        raise ValueError('action should be one of GET, POST, PUT, DELETE') # cover 100

    def create_el(self, payload):
        log.debug(payload)
        payload = self._to_mongo(payload)
        try:
            result = self.dbc.insert_one(payload)
        except pymongo.errors.DuplicateKeyError: # cover 100
            raise APIConflictException('Object with id {} already exists.'.format(payload['_id']))
        return result

    def update_el(self, _id, payload, unset_payload=None, recursive=False, r_payload=None, replace_metadata=False):
        replace = None
        if replace_metadata: # cover 100
            replace = {}
            if payload.get('info') is not None:
                replace['info'] = util.mongo_sanitize_fields(payload.pop('info'))
            if payload.get('subject') is not None and payload['subject'].get('info') is not None:
                replace['subject.info'] = util.mongo_sanitize_fields(payload['subject'].pop('info'))

        update = {}

        if payload is not None:
            payload = self._to_mongo(payload)
            update['$set'] = util.mongo_dict(payload)

        if unset_payload is not None:
            update['$unset'] = util.mongo_dict(unset_payload)

        if replace is not None:
            update['$set'].update(replace) # cover 100

        if self.use_object_id:
            try:
                _id = bson.ObjectId(_id)
            except bson.InvalidId as e: # cover 100
                raise APIStorageException(e.message)
        if recursive and r_payload is not None:
            hierarchy.propagate_changes(self.cont_name, _id, {}, {'$set': util.mongo_dict(r_payload)})
        return self.dbc.update_one({'_id': _id}, update)

    def delete_el(self, _id):
        if self.use_object_id:
            try:
                _id = bson.ObjectId(_id)
            except bson.InvalidId as e: # cover 100
                raise APIStorageException(e.message)
        return self.dbc.delete_one({'_id':_id})

    def get_el(self, _id, projection=None, fill_defaults=False):
        if self.use_object_id:
            try:
                _id = bson.ObjectId(_id)
            except bson.InvalidId as e: # cover 100
                raise APIStorageException(e.message)
        cont = self._from_mongo(self.dbc.find_one(_id, projection))
        if fill_defaults:
            cont =  self._fill_default_values(cont)
        return cont

    def get_all_el(self, query, user, projection, fill_defaults=False):
        if user:
            if query.get('permissions'):
                query['$and'] = [{'permissions': {'$elemMatch': user}}, {'permissions': query.pop('permissions')}] # cover 100
            else:
                query['permissions'] = {'$elemMatch': user}
        log.debug(query)
        log.debug(projection)

        # if projection includes files.info, add new key `info_exists`
        if projection and 'files.info' in projection:
            replace_info_with_bool = True
            projection.pop('files.info')
        else:
            replace_info_with_bool = False

        results = list(self.dbc.find(query, projection))
        for cont in results:
            cont = self._from_mongo(cont)
            if fill_defaults:
                cont =  self._fill_default_values(cont)
            if replace_info_with_bool:
                for f in cont.get('files', []):
                    f['info_exists'] = bool(f.pop('info', False))
        return results
