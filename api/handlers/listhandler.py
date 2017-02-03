import os
import copy
import datetime
import urllib

from .. import base
from .. import util
from .. import files
from .. import rules
from .. import config
from .. import validators
from .. import tempdir as tempfile
from ..auth import listauth, always_ok
from ..dao import liststorage
from ..dao import APIStorageException

log = config.log

def initialize_list_configurations():
    """
    This configurations are used by the ListHandler class to load the storage, the permissions checker
    and the json schema validators used to handle a request.

    "use_object_id" implies that the container ids are converted to ObjectId
    "get_full_container" allows the handler to load the full content of the container and not only the sublist element (this is used for permissions for example)
    """
    container_default_configurations = {
        'tags': {
            'storage': liststorage.StringListStorage,
            'permchecker': listauth.default_sublist,
            'use_object_id': True,
            'storage_schema_file': 'tag.json',
            'input_schema_file': 'tag.json'
        },
        'files': {
            'storage': liststorage.ListStorage,
            'permchecker': listauth.default_sublist,
            'use_object_id': True,
            'storage_schema_file': 'file.json',
            'input_schema_file': 'file.json'
        },
        'permissions': {
            'storage': liststorage.ListStorage,
            'permchecker': listauth.permissions_sublist,
            'use_object_id': True,
            'get_full_container': True,
            'storage_schema_file': 'permission.json',
            'input_schema_file': 'permission.json'
        },
        'notes': {
            'storage': liststorage.ListStorage,
            'permchecker': listauth.notes_sublist,
            'use_object_id': True,
            'storage_schema_file': 'note.json',
            'input_schema_file': 'note.json'
        },
    }
    list_handler_configurations = {
        'groups': {
            'roles':{
                'storage': liststorage.ListStorage,
                'permchecker': listauth.group_roles_sublist,
                'use_object_id': False,
                'get_full_container': True,
                'storage_schema_file': 'permission.json',
                'input_schema_file': 'permission.json'
            }
        },
        'projects': copy.deepcopy(container_default_configurations),
        'sessions': copy.deepcopy(container_default_configurations),
        'acquisitions': copy.deepcopy(container_default_configurations),
        'collections': copy.deepcopy(container_default_configurations)
    }
    # preload the Storage instances for all configurations
    for cont_name, cont_config in list_handler_configurations.iteritems():
        for list_name, list_config in cont_config.iteritems():
            storage_class = list_config['storage']
            storage = storage_class(
                cont_name,
                list_name,
                use_object_id=list_config.get('use_object_id', False)
            )
            list_config['storage'] = storage
    return list_handler_configurations


list_handler_configurations = initialize_list_configurations()


class ListHandler(base.RequestHandler):
    """
    This class handle operations on a generic sublist of a container like tags, group roles, user permissions, etc.

    The pattern used is:
    1) initialize request
    2) exec request
    3) check and return result

    Specific behaviors (permissions checking logic for authenticated and not superuser users, storage interaction)
    are specified in the routes defined in api.py
    """

    def __init__(self, request=None, response=None):
        super(ListHandler, self).__init__(request, response)
        self.list_handler_configurations = list_handler_configurations

    def get(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        container, permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)
        try:
            result = keycheck(permchecker(storage.exec_op))('GET', _id, query_params=kwargs)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result is None:
            self.abort(404, 'Element not found in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
        return result

    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        container, permchecker, storage, mongo_validator, payload_validator, keycheck = self._initialize_request(cont_name, list_name, _id)

        payload = self.request.json_body
        payload_validator(payload, 'POST')
        result = keycheck(mongo_validator(permchecker(storage.exec_op)))('POST', _id=_id, payload=payload)

        if result.modified_count == 1:
            return {'modified':result.modified_count}
        else:
            self.abort(404, 'Element not added in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        container, permchecker, storage, mongo_validator, payload_validator, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        payload = self.request.json_body
        payload_validator(payload, 'PUT')
        try:
            result = keycheck(mongo_validator(permchecker(storage.exec_op)))('PUT', _id=_id, query_params=kwargs, payload=payload)
        except APIStorageException as e:
            self.abort(400, e.message)
        # abort if the query of the update wasn't able to find any matching documents
        if result.matched_count == 0:
            self.abort(404, 'Element not updated in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
        else:
            return {'modified':result.modified_count}

    def delete(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        container, permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)
        try:
            result = keycheck(permchecker(storage.exec_op))('DELETE', _id, query_params=kwargs)
        except APIStorageException as e:
            self.abort(400, e.message)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not removed from list {} in container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def _initialize_request(self, cont_name, list_name, _id, query_params=None):
        """
        This method loads:
        1) the container that will be modified
        2) the storage class that will handle the database actions
        3) the permission checker decorator that will be used
        4) the payload_validator checking the payload sent by the client against a json schema
        5) the mongo_validator that will check what will be sent to mongo against a json schema
        6) the keycheck decorator validating the request key
        """
        config = self.list_handler_configurations[cont_name][list_name]
        storage = config['storage']
        permchecker = config['permchecker']
        if config.get('get_full_container'):
             query_params = None
        container = storage.get_container(_id, query_params)
        if container is not None:
            if self.superuser_request:
                permchecker = always_ok
            elif self.public_request:
                permchecker = listauth.public_request(self, container)
            else:
                permchecker = permchecker(self, container)
        else:
            self.abort(404, 'Element {} not found in container {}'.format(_id, storage.cont_name))
        mongo_validator = validators.mongo_from_schema_file(self, config.get('storage_schema_file'))
        input_validator = validators.payload_from_schema_file(self, config.get('input_schema_file'))
        keycheck = validators.key_check(self, config.get('storage_schema_file'))
        return container, permchecker, storage, mongo_validator, input_validator, keycheck


class PermissionsListHandler(ListHandler):
    """
    PermissionsListHandler overrides post, put and delete methods of ListHandler to propagate permissions
    """
    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(PermissionsListHandler, self).post(cont_name, list_name, **kwargs)
        if cont_name == 'projects':
            self._propagate_project_permissions(_id)
        return result

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(PermissionsListHandler, self).put(cont_name, list_name, **kwargs)
        if cont_name == 'projects':
            self._propagate_project_permissions(_id)
        return result

    def delete(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(PermissionsListHandler, self).delete(cont_name, list_name, **kwargs)
        if cont_name == 'projects':
            self._propagate_project_permissions(_id)
        return result

    def _propagate_project_permissions(self, _id):
        """
        method to propagate permissions from a project to its sessions and acquisitions
        """
        try:
            log.debug(_id)
            oid = util.ObjectId(_id)
            update = {
                'permissions': config.db.projects.find_one(oid)['permissions']
            }
            session_ids = [s['_id'] for s in config.db.sessions.find({'project': oid}, [])]
            config.db.sessions.update_many({'project': oid}, {'$set': update})
            config.db.acquisitions.update_many({'session': {'$in': session_ids}}, {'$set': update})
            acq_ids = [a['_id'] for a in config.db.acquisitions.find({'session': {'$in': session_ids}})]
            config.db.project_snapshots.update_many({'original': oid}, {'$set': update})
            config.db.session_snapshots.update_many({'original': {'$in': session_ids}}, {'$set': update})
            config.db.acquisition_snapshots.update_many({'original': {'$in': acq_ids}}, {'$set': update})
        except:
            self.abort(500, 'permissions not propagated from project {} to sessions'.format(_id))


class NotesListHandler(ListHandler):
    """
    NotesListHandler overrides post, put methods of ListHandler to add custom fields to the payload.
    e.g. _id, user, created, etc.
    """

    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        container, permchecker, storage, mongo_validator, input_validator, keycheck = self._initialize_request(cont_name, list_name, _id)

        payload = self.request.json_body
        input_validator(payload, 'POST')
        payload['_id'] = payload.get('_id') or str(util.ObjectId())
        payload['user'] = payload.get('user', self.uid)
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        if payload.get('timestamp'):
            payload['timestamp'] = dateutil.parser.parse(payload['timestamp'])
        result = keycheck(mongo_validator(permchecker(storage.exec_op)))('POST', _id=_id, payload=payload)

        if result.modified_count == 1:
            return {'modified':result.modified_count}
        else:
            self.abort(404, 'Element not added in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        container, permchecker, storage, mongo_validator, input_validator, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        payload = self.request.json_body
        input_validator(payload, 'PUT')
        payload['modified'] = datetime.datetime.utcnow()
        if payload.get('timestamp'):
            payload['timestamp'] = dateutil.parser.parse(payload['timestamp'])
        result = keycheck(mongo_validator(permchecker(storage.exec_op)))('PUT', _id=_id, query_params=kwargs, payload=payload)
        # abort if the query of the update wasn't able to find any matching documents
        if result.matched_count == 0:
            self.abort(404, 'Element not updated in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
        else:
            return {'modified':result.modified_count}



class FileListHandler(ListHandler):
    """
    This class implements a more specific logic for list of files as the api needs to interact with the filesystem.
    """

    def __init__(self, request=None, response=None):
        super(FileListHandler, self).__init__(request, response)

    def _check_ticket(self, ticket_id, _id, filename):
        ticket = config.db.downloads.find_one({'_id': ticket_id})
        if not ticket:
            self.abort(404, 'no such ticket')
        if ticket['target'] != _id or ticket['filename'] != filename or ticket['ip'] != self.request.client_addr:
            self.abort(400, 'ticket not for this resource or source IP')
        return ticket

    def get(self, cont_name, list_name, **kwargs):
        kwargs['name'] = urllib.quote(kwargs.get('name'), '')
        log.error('{} {} {}'.format(cont_name, list_name, kwargs))
        _id = kwargs.pop('cid')
        container, permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id)
        list_name = storage.list_name
        filename = kwargs.get('name')
        ticket_id = self.get_param('ticket')
        if ticket_id:
            ticket = self._check_ticket(ticket_id, _id, filename)
            try:
                fileinfo = keycheck(storage.exec_op)('GET', _id, query_params=kwargs)
            except APIStorageException as e:
                self.abort(400, e.message)
        else:
            try:
                fileinfo = keycheck(permchecker(storage.exec_op))('GET', _id, query_params=kwargs)
            except APIStorageException as e:
                self.abort(400, e.message)
        if not fileinfo:
            self.abort(404, 'no such file')
        hash_ = self.get_param('hash')
        if hash_ and hash_ != fileinfo['hash']:
            self.abort(409, 'file exists, hash mismatch')
        filepath = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
        if self.get_param('ticket') == '':    # request for download ticket
            ticket = util.download_ticket(self.request.client_addr, 'file', _id, filename, fileinfo['size'])
            return {'ticket': config.db.downloads.insert_one(ticket).inserted_id}
        else:                                       # authenticated or ticketed (unauthenticated) download
            zip_member = self.get_param('member')
            if self.is_true('info'):
                try:
                    with zipfile.ZipFile(filepath) as zf:
                        return [(zi.filename, zi.file_size, datetime.datetime(*zi.date_time)) for zi in zf.infolist()]
                except zipfile.BadZipfile:
                    self.abort(400, 'not a zip file')
            elif self.is_true('comment'):
                try:
                    with zipfile.ZipFile(filepath) as zf:
                        self.response.write(zf.comment)
                except zipfile.BadZipfile:
                    self.abort(400, 'not a zip file')
            elif zip_member:
                try:
                    with zipfile.ZipFile(filepath) as zf:
                        self.response.headers['Content-Type'] = util.guess_mimetype(zip_member)
                        self.response.write(zf.open(zip_member).read())
                except zipfile.BadZipfile:
                    self.abort(400, 'not a zip file')
                except KeyError:
                    self.abort(400, 'zip file contains no such member')
            else:
                self.response.app_iter = open(filepath, 'rb')
                self.response.headers['Content-Length'] = str(fileinfo['size']) # must be set after setting app_iter
                if self.is_true('view'):
                    self.response.headers['Content-Type'] = str(util.guess_mimetype(fileinfo.get('name')))
                else:
                    self.response.headers['Content-Type'] = 'application/octet-stream'
                    self.response.headers['Content-Disposition'] = 'attachment; filename="' + os.path.basename(urllib.url2pathname(filename)) + '"'

    def delete(self, cont_name, list_name, **kwargs):
        kwargs['name'] = urllib.quote(kwargs.get('name'), '')
        filename = kwargs.get('name')
        _id = kwargs.get('cid')
        result = super(FileListHandler, self).delete(cont_name, list_name, **kwargs)
        return result

    def post(self, cont_name, list_name, **kwargs):
        force = self.is_true('force')
        _id = kwargs.pop('cid')
        container, permchecker, storage, mongo_validator, payload_validator, keycheck = self._initialize_request(cont_name, list_name, _id)

        result = None
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            file_store = files.FileStore(self.request, tempdir_path, filename=kwargs.get('name'))
            payload = file_store.payload
            file_datetime = datetime.datetime.utcnow()
            file_properties = {
                'name': file_store.filename,
                'size': file_store.size,
                'hash': file_store.hash,
                'created': file_datetime,
                'modified': file_datetime,
            }
            if file_store.metadata:
                file_properties['metadata'] = file_store.metadata
            if file_store.tags:
                file_properties['tags'] = file_store.tags
            dest_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(file_properties['hash']))
            query_params = None
            if not force:
                method = 'POST'
            else:
                filename = file_store.filename
                filepath = file_store.path
                for f in container.get('files', []):
                    if f['name'] == filename:
                        if file_store.identical(filepath, f['hash']):
                            log.debug('Dropping    %s (identical)' % filename)
                            os.remove(filepath)
                            return {'modified': 0}
                        else:
                            log.debug('Replacing   %s' % filename)
                            method = 'PUT'
                            query_params = {'name':filename}
                        break
                else:
                    method = 'POST'
            file_store.move_file(dest_path)
            payload_validator(payload, method)
            payload.update(file_properties)
            result = keycheck(mongo_validator(permchecker(storage.exec_op)))(method, _id=_id, query_params=query_params, payload=payload)
            if not result or result.modified_count != 1:
                self.abort(404, 'Element not added in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
            rules.create_jobs(config.db, container, cont_name[:-1], file_properties)
        return {'modified': result.modified_count}
