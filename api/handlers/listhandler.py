import os
import bson
import copy
import datetime
import dateutil
import json
import uuid
import zipfile

import fs.path

from ..web import base
from .. import config, files, upload, util, validators
from ..auth import listauth, always_ok
from ..dao import noop
from ..dao import liststorage
from ..dao import containerutil
from ..web.errors import APIStorageException, APIPermissionException
from ..web.request import AccessType


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
            'storage': liststorage.FileStorage,
            'permchecker': listauth.files_sublist,
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
    list_container_configurations = {
        'groups': {
            'permissions':{
                'storage': liststorage.ListStorage,
                'permchecker': listauth.group_permissions_sublist,
                'use_object_id': False,
                'get_full_container': True,
                'storage_schema_file': 'permission.json',
                'input_schema_file': 'permission.json'
            },
            'tags': {
                'storage': liststorage.StringListStorage,
                'permchecker': listauth.group_tags_sublist,
                'use_object_id': False,
                'storage_schema_file': 'tag.json',
                'input_schema_file': 'tag.json'
            },
        },
        'projects': copy.deepcopy(container_default_configurations),
        'sessions': copy.deepcopy(container_default_configurations),
        'acquisitions': copy.deepcopy(container_default_configurations),
        'collections': copy.deepcopy(container_default_configurations),
        'analyses': copy.deepcopy(container_default_configurations),
    }
    # preload the Storage instances for all configurations
    for cont_name, cont_config in list_container_configurations.iteritems():
        for list_name, list_config in cont_config.iteritems():
            storage_class = list_config['storage']
            if list_name == 'files':
                storage = storage_class(cont_name)
            else:
                storage = storage_class(
                    cont_name,
                    list_name,
                    use_object_id=list_config.get('use_object_id', False)
                )
            list_config['storage'] = storage
    return list_container_configurations


list_handler_configurations = initialize_list_configurations()


class ListHandler(base.RequestHandler):
    """
    This class handle operations on a generic sublist of a container like tags, group permissions, user permissions, etc.

    The pattern used is:
    1) initialize request
    2) exec request
    3) check and return result

    Specific behaviors (permissions checking logic for authenticated and not superuser users, storage interaction)
    are specified in the routes defined in api.py
    """

    def __init__(self, request=None, response=None):
        super(ListHandler, self).__init__(request, response)

    def get(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)
        try:
            result = keycheck(permchecker(storage.exec_op))('GET', _id, query_params=kwargs)
        except APIStorageException as e:
            self.abort(400, e.message)

        if result is None:
            self.abort(404, 'Element not found in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
        return result

    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, mongo_validator, payload_validator, keycheck = self._initialize_request(cont_name, list_name, _id)

        payload = self.request.json_body
        payload_validator(payload, 'POST')
        result = keycheck(mongo_validator(permchecker(storage.exec_op)))('POST', _id=_id, payload=payload)

        if result.modified_count == 1:
            return {'modified':result.modified_count}
        else:
            self.abort(404, 'Element not added in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, mongo_validator, payload_validator, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

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
        permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)
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
        conf = list_handler_configurations[cont_name][list_name]
        storage = conf['storage']
        permchecker = conf['permchecker']
        if conf.get('get_full_container'):
            query_params = None
        container = storage.get_container(_id, query_params)
        if container is not None:
            if self.superuser_request or self.user_is_admin:
                permchecker = always_ok
            elif self.public_request:
                permchecker = listauth.public_request(self, container)
            else:
                permchecker = permchecker(self, container)
        else:
            self.abort(404, 'Element {} not found in container {}'.format(_id, storage.cont_name))

        mongo_schema_uri = validators.schema_uri('mongo', conf.get('storage_schema_file'))
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        keycheck = validators.key_check(mongo_schema_uri)
        input_schema_uri = validators.schema_uri('input', conf.get('input_schema_file'))
        input_validator = validators.from_schema_path(input_schema_uri)
        return permchecker, storage, mongo_validator, input_validator, keycheck


class PermissionsListHandler(ListHandler):
    """
    PermissionsListHandler overrides post, put and delete methods of ListHandler to propagate permissions
    """
    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(PermissionsListHandler, self).post(cont_name, list_name, **kwargs)
        payload = self.request.json_body

        if cont_name == 'groups' and self.request.params.get('propagate') =='true':
            self._propagate_permissions(cont_name, _id, query={'permissions._id' : payload['_id']}, update={'$set': {'permissions.$.access': payload['access']}})
            self._propagate_permissions(cont_name, _id, query={'permissions._id': {'$ne': payload['_id']}}, update={'$addToSet': {'permissions': payload}})
        elif cont_name != 'groups':
            self._propagate_permissions(cont_name, _id)
        return result

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')

        result = super(PermissionsListHandler, self).put(cont_name, list_name, **kwargs)
        payload = self.request.json_body
        payload['_id'] = kwargs.get('_id')
        if cont_name == 'groups' and self.request.params.get('propagate') =='true':
            self._propagate_permissions(cont_name, _id, query={'permissions._id' : payload['_id']}, update={'$set': {'permissions.$.access': payload['access']}})
            self._propagate_permissions(cont_name, _id, query={'permissions._id': {'$ne': payload['_id']}}, update={'$addToSet': {'permissions': payload}})
        elif cont_name != 'groups':
            self._propagate_permissions(cont_name, _id)
        return result

    def delete(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(PermissionsListHandler, self).delete(cont_name, list_name, **kwargs)

        if cont_name == 'groups' and self.request.params.get('propagate') =='true':
            self._propagate_permissions(cont_name, _id, query={'permissions._id' : kwargs.get('_id')}, update={'$pull' : {'permissions': {'_id': kwargs.get('_id')}}})
        elif cont_name != 'groups':
            self._propagate_permissions(cont_name, _id)
        return result

    def _propagate_permissions(self, cont_name, _id, query=None, update=None):
        """
        method to propagate permissions from a container/group to its sessions and acquisitions
        """
        if cont_name == 'groups':
            try:
                containerutil.propagate_changes(cont_name, _id, query, update)
            except APIStorageException as e:
                self.abort(400, e.message)
        elif cont_name == 'projects':
            try:
                oid = bson.ObjectId(_id)
                update = {'$set': {
                    'permissions': config.db[cont_name].find_one({'_id': oid}, {'permissions': 1})['permissions']
                }}
                containerutil.propagate_changes(cont_name, oid, {}, update)
            except APIStorageException:
                self.abort(500, 'permissions not propagated from {} {} down hierarchy'.format(cont_name, _id))


class NotesListHandler(ListHandler):
    """
    NotesListHandler overrides post, put methods of ListHandler to add custom fields to the payload.
    e.g. _id, user, created, etc.
    """

    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, mongo_validator, input_validator, keycheck = self._initialize_request(cont_name, list_name, _id)

        payload = self.request.json_body
        input_validator(payload, 'POST')
        payload['_id'] = payload.get('_id') or str(bson.objectid.ObjectId())
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
        permchecker, storage, mongo_validator, input_validator, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

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


class TagsListHandler(ListHandler):
    """
    TagsListHandler overrides put, delete methods of ListHandler to propagate changes to group tags
    If a tag is renamed or deleted at the group level, project, session and acquisition tags will also be renamed/deleted
    """

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(TagsListHandler, self).put(cont_name, list_name, **kwargs)
        if cont_name == 'groups':
            payload = self.request.json_body
            current_value = kwargs.get('value')
            new_value = payload.get('value')
            query = {'$and':[{'tags': current_value}, {'tags': {'$ne': new_value}}]}
            update = {'$set': {'tags.$': new_value}}
            self._propagate_group_tags(cont_name, _id, query, update)
        return result

    def delete(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(TagsListHandler, self).delete(cont_name, list_name, **kwargs)
        if cont_name == 'groups':
            deleted_tag = kwargs.get('value')
            query = {}
            update = {'$pull': {'tags': deleted_tag}}
            self._propagate_group_tags(cont_name, _id, query, update)
        return result

    def _propagate_group_tags(self, cont_name, _id, query, update):
        """
        method to propagate tag changes from a group to its projects, sessions and acquisitions
        """
        try:
            containerutil.propagate_changes(cont_name, _id, query, update)
        except APIStorageException:
            self.abort(500, 'tag change not propagated from group {}'.format(_id))


class FileListHandler(ListHandler):
    """
    This class implements a more specific logic for list of files as the api needs to interact with the filesystem.
    """

    def __init__(self, request=None, response=None):
        super(FileListHandler, self).__init__(request, response)

    def _create_ticket(self):
        payload = self.request.json_body
        metadata = payload.get('metadata', None)
        filename = payload.get('filename', None)

        if not (metadata or filename):
            self.abort(404, 'metadata and filename are required')

        tempdir = str(uuid.uuid4())
        # Upload into a temp folder, so we will be able to cleanup
        signed_url = files.get_signed_url(fs.path.join('tmp', tempdir, filename), config.fs, purpose='upload')

        if not signed_url:
            self.abort(405, 'Signed URLs are not supported with the current storage backend')

        ticket = util.upload_ticket(self.request.client_addr, self.origin, tempdir, filename, metadata)
        return {'ticket': config.db.uploads.insert_one(ticket).inserted_id,
                'upload_url': signed_url}

    def _check_ticket(self, ticket_id, _id, filename):
        ticket = config.db.downloads.find_one({'_id': ticket_id})
        if not ticket:
            self.abort(404, 'no such ticket')
        if ticket['target'] != _id or ticket['filename'] != filename or ticket['ip'] != self.request.client_addr:
            self.abort(400, 'ticket not for this resource or source IP')
        return ticket

    def _check_upload_ticket(self, ticket_id):
        ticket = config.db.uploads.find_one({'_id': ticket_id})
        if not ticket:
            self.abort(404, 'no such ticket')
        if ticket['ip'] != self.request.client_addr:
            self.abort(400, 'ticket not for this resource or source IP')
        return ticket

    @staticmethod
    def build_zip_info(file_path, file_system):
        """
        Builds a json response containing member and comment info for a zipfile
        """
        with file_system.open(file_path, 'rb') as f:
            with zipfile.ZipFile(f) as zf:
                info = {
                    'comment': zf.comment,
                    'members': []
                }
                for zi in zf.infolist():
                    info['members'].append({
                        'path': zi.filename,
                        'size': zi.file_size,
                        'timestamp': datetime.datetime(*zi.date_time),
                        'comment': zi.comment
                    })

                return info

    def get(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id)
        list_name = storage.list_name
        filename = kwargs.get('name')

        # Check ticket id and skip permissions check if it clears
        ticket_id = self.get_param('ticket')
        ticket = None
        if ticket_id:
            ticket = self._check_ticket(ticket_id, _id, filename)
            if not self.origin.get('id'):
                # If we don't have an origin with this request, use the ticket's origin
                self.origin = ticket.get('origin')
            permchecker = always_ok

        # Grab fileinfo from db
        try:
            fileinfo = keycheck(permchecker(storage.exec_op))('GET', _id, query_params=kwargs)
        except APIStorageException as e:
            self.abort(400, e.message)
        if not fileinfo:
            self.abort(404, 'no such file')

        hash_ = self.get_param('hash')
        if hash_ and hash_ != fileinfo['hash']:
            self.abort(409, 'file exists, hash mismatch')

        file_path, file_system = files.get_valid_file(fileinfo)

        # Request for download ticket
        if self.get_param('ticket') == '':
            ticket = util.download_ticket(self.request.client_addr, self.origin, 'file', _id, filename, fileinfo['size'])
            return {'ticket': config.db.downloads.insert_one(ticket).inserted_id}

        # Request for info about zipfile
        elif self.is_true('info'):
            try:
                info = self.build_zip_info(file_path, file_system)
                return info
            except zipfile.BadZipfile:
                self.abort(400, 'not a zip file')

        # Request to download zipfile member
        elif self.get_param('member') is not None:
            zip_member = self.get_param('member')
            try:
                with file_system.open(file_path, 'rb') as f:
                    with zipfile.ZipFile(f) as zf:
                        self.response.headers['Content-Type'] = util.guess_mimetype(zip_member)
                        self.response.write(zf.open(zip_member).read())
            except zipfile.BadZipfile:
                self.abort(400, 'not a zip file')
            except KeyError:
                self.abort(400, 'zip file contains no such member')
            # log download if we haven't already for this ticket
            if ticket:
                if not ticket.get('logged', False):
                    self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id, filename=fileinfo['name'])
                    config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
            else:
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id, filename=fileinfo['name'])

        # Authenticated or ticketed download request
        else:
            signed_url = files.get_signed_url(file_path, file_system, filename=filename)
            if signed_url:
                self.redirect(signed_url)
            else:
                range_header = self.request.headers.get('Range', '')
                try:
                    if not self.is_true('view'):
                        raise util.RangeHeaderParseError('Feature flag not set')

                    ranges = util.parse_range_header(range_header)
                    for first, last in ranges:
                        if first > fileinfo['size'] - 1:
                            self.abort(416, 'Invalid range')

                        if last > fileinfo['size'] - 1:
                            raise util.RangeHeaderParseError('Invalid range')

                except util.RangeHeaderParseError:
                    self.response.app_iter = file_system.open(file_path, 'rb')
                    self.response.headers['Content-Length'] = str(fileinfo['size'])  # must be set after setting app_iter

                    if self.is_true('view'):
                        self.response.headers['Content-Type'] = str(fileinfo.get('mimetype', 'application/octet-stream'))
                    else:
                        self.response.headers['Content-Type'] = 'application/octet-stream'
                        self.response.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'
                else:
                    self.response.status = 206
                    if len(ranges) > 1:
                        self.response.headers['Content-Type'] = 'multipart/byteranges; boundary=%s' % self.request.id
                    else:
                        self.response.headers['Content-Type'] = str(
                            fileinfo.get('mimetype', 'application/octet-stream'))
                        self.response.headers['Content-Range'] = 'bytes %s-%s/%s' % (str(ranges[0][0]),
                                                                                     str(ranges[0][1]),
                                                                                     str(fileinfo['size']))
                    with file_system.open(file_path, 'rb') as f:
                        for first, last in ranges:
                            mode = os.SEEK_SET
                            if first < 0:
                                mode = os.SEEK_END
                                length = abs(first)
                            elif last is None:
                                length = fileinfo['size'] - first
                            else:
                                if last > fileinfo['size']:
                                    length = fileinfo['size'] - first
                                else:
                                    length = last - first + 1

                            f.seek(first, mode)
                            data = f.read(length)

                            if len(ranges) > 1:
                                self.response.write('--%s\n' % self.request.id)
                                self.response.write('Content-Type: %s\n' % str(
                                    fileinfo.get('mimetype', 'application/octet-stream')))
                                self.response.write('Content-Range: %s' % 'bytes %s-%s/%s\n' % (str(first),
                                                                                                str(last),
                                                                                                str(fileinfo['size'])))
                                self.response.write('\n')
                                self.response.write(data)
                                self.response.write('\n')
                            else:
                                self.response.write(data)

            # log download if we haven't already for this ticket
            if ticket:
                # recheck ticket for logged flag
                ticket = config.db.downloads.find_one({'_id': ticket_id})
                if not ticket.get('logged', False):
                    self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id, filename=fileinfo['name'])
                    config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
            else:
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id, filename=fileinfo['name'])


    def get_info(self, cont_name, list_name, **kwargs):
        _id = kwargs['cid']
        filename = kwargs['name']
        result = super(FileListHandler,self).get(cont_name, list_name, **kwargs)
        self.log_user_access(AccessType.view_file, cont_name=cont_name, cont_id=_id, filename=filename)
        return result


    def modify_info(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, _ = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        payload = self.request.json_body

        validators.validate_data(payload, 'info_update.json', 'input', 'POST')

        try:
            permchecker(noop)('PUT', _id=_id, query_params=kwargs, payload=payload)
            result = storage.modify_info(_id, kwargs, payload)
        except APIStorageException as e:
            self.abort(400, e.message)
        # abort if the query of the update wasn't able to find any matching documents
        if result.matched_count == 0:
            self.abort(404, 'Element not updated in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
        else:
            return {'modified':result.modified_count}

    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        # Authorize
        permchecker, _, _, _, _ = self._initialize_request(containerutil.pluralize(cont_name), list_name, _id)
        permchecker(noop)('POST', _id=_id)

        # Request for upload ticket
        if self.get_param('ticket') == '':
            return self._create_ticket()

        # Check ticket id and skip permissions check if it clears
        ticket_id = self.get_param('ticket')
        if ticket_id:
            ticket = self._check_upload_ticket(ticket_id)
            if not self.origin.get('id'):
                # If we don't have an origin with this request, use the ticket's origin
                self.origin = ticket.get('origin')

            file_fields = [
                util.dotdict({
                    'filename': ticket['filename']
                })
            ]

            return upload.process_upload(self.request, upload.Strategy.targeted, metadata=ticket['metadata'], origin=self.origin,
                                         container_type=containerutil.singularize(cont_name),
                                         id_=_id, file_fields=file_fields, tempdir=ticket['tempdir'])
        else:
            return upload.process_upload(self.request, upload.Strategy.targeted, container_type=containerutil.singularize(cont_name), id_=_id, origin=self.origin)

    @validators.verify_payload_exists
    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, _ = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        payload = self.request.json_body
        validators.validate_data(payload, 'file-update.json', 'input', 'PUT')

        result = permchecker(storage.exec_op)('PUT', _id=_id, query_params=kwargs, payload=payload)
        return result

    def delete(self, cont_name, list_name, **kwargs):
        # Overriding base class delete to audit action before completion
        _id = kwargs.pop('cid')
        filename = kwargs['name']
        permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        permchecker(noop)('DELETE', _id=_id, query_params=kwargs)

        if cont_name == 'acquisitions':
            analyses = containerutil.get_referring_analyses(cont_name, _id, filename=filename)
            if analyses:
                analysis_ids = [str(a['_id']) for a in analyses]
                raise APIPermissionException('Cannot delete file {} referenced by analyses {}'.format(filename, analysis_ids),
                    errors={'reason': 'analysis_conflict'})

        self.log_user_access(AccessType.delete_file, cont_name=cont_name, cont_id=_id, filename=filename)
        try:
            result = keycheck(storage.exec_op)('DELETE', _id, query_params=kwargs)
        except APIStorageException as e:
            self.abort(400, e.message)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not removed from list {} in container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def _check_packfile_token(self, project_id, token_id, check_user=True):
        """
        Check and update a packfile token assertion.
        """

        if token_id is None:
            raise Exception('Upload token is required')

        query = {
            'type': 'packfile',
            'project': project_id,
            '_id': token_id,
        }

        # Server-Sent Events are fired in the browser in such a way that one cannot dictate their headers.
        # For these endpoints, authentication must be disabled because the normal Authorization header will not be present.
        # In this case, the document id will serve instead.
        if check_user:
            query['user'] = self.uid

        # Check for correct token
        result = config.db['tokens'].find_one(query)

        if result is None:
            raise Exception('Invalid or expired upload token')

        # Update token timestamp
        config.db['tokens'].update_one({
            '_id': token_id,
        }, {
            '$set': {
                'modified': datetime.datetime.utcnow()
            }
        })

    def packfile_start(self, cont_name, **kwargs):
        """
        Declare intent to upload a packfile to a project, and recieve an upload token identifier.
        """

        _id = kwargs.pop('cid')

        if cont_name != 'projects':
            raise Exception('Packfiles can only be targeted at projects')

        # Authorize: confirm project exists
        project = config.db['projects'].find_one({'_id': bson.ObjectId(_id), 'deleted': {'$exists': False}})

        if project is None:
            raise Exception('Project ' + _id + ' does not exist')

        # Authorize: confirm user has admin/write perms
        if not self.superuser_request:
            perms = project.get('permissions', [])

            for p in perms:
                if p['_id'] == self.uid and p['access'] in ('rw', 'admin'):
                    break
            else:
                raise Exception('Not authorized')

        timestamp = datetime.datetime.utcnow()

        # Save token for stateful uploads
        result = config.db['tokens'].insert_one({
            '_id': str(uuid.uuid4()),
            'type': 'packfile',
            'user': self.uid,
            'project': _id,
            'created': timestamp,
            'modified': timestamp,
        })

        return {
            'token': str(result.inserted_id)
        }

    def packfile(self, **kwargs):
        """
        Add files to an in-progress packfile.
        """

        project_id = kwargs.pop('cid')
        token_id = self.request.GET.get('token')
        self._check_packfile_token(project_id, token_id)

        return upload.process_upload(self.request, upload.Strategy.token, origin=self.origin, context={'token': token_id})

    def packfile_end(self, **kwargs):
        """
        Complete and save an uploaded packfile.
        """

        project_id = kwargs.pop('cid')
        token_id = self.request.GET.get('token')
        self._check_packfile_token(project_id, token_id, check_user=False)

        # Because this is an SSE endpoint, there is no form-post. Instead, read JSON data from request param
        metadata = json.loads(self.request.GET.get('metadata'))

        return upload.process_upload(self.request, upload.Strategy.packfile, origin=self.origin, context={'token': token_id}, response=self.response, metadata=metadata)
