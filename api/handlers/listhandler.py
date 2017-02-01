import os
import bson
import copy
import datetime
import dateutil
import json
import uuid
import zipfile

from ..web import base
from .. import config
from .. import upload
from .. import download
from .. import util
from .. import validators
from ..auth import listauth, always_ok
from ..dao import noop
from ..dao import liststorage
from ..dao import APIStorageException
from ..dao import hierarchy
from .modalityhandler import ModalityHandler
from ..web.request import log_access, AccessType


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
        'analyses': {
            'storage': liststorage.AnalysesStorage,
            'permchecker': listauth.default_sublist,
            'use_object_id': True,
            'storage_schema_file': 'analysis.json',
            'input_schema_file': 'analysis.json'
        }
    }
    list_container_configurations = {
        'groups': {
            'roles':{
                'storage': liststorage.ListStorage,
                'permchecker': listauth.group_roles_sublist,
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
        'collections': copy.deepcopy(container_default_configurations)
    }
    # preload the Storage instances for all configurations
    for cont_name, cont_config in list_container_configurations.iteritems():
        for list_name, list_config in cont_config.iteritems():
            storage_class = list_config['storage']
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
            if self.superuser_request:
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
        self._propagate_project_permissions(cont_name, _id)
        return result

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')

        result = super(PermissionsListHandler, self).put(cont_name, list_name, **kwargs)
        self._propagate_project_permissions(cont_name, _id)
        return result

    def delete(self, cont_name, list_name, **kwargs):
        _id = kwargs.get('cid')
        result = super(PermissionsListHandler, self).delete(cont_name, list_name, **kwargs)
        self._propagate_project_permissions(cont_name, _id)
        return result

    def _propagate_project_permissions(self, cont_name, _id):
        """
        method to propagate permissions from a project to its sessions and acquisitions
        """
        if cont_name == 'projects':
            try:
                oid = bson.ObjectId(_id)
                update = {'$set': {
                    'permissions': config.db.projects.find_one({'_id': oid},{'permissions': 1})['permissions']
                }}
                hierarchy.propagate_changes(cont_name, oid, {}, update)
            except APIStorageException:
                self.abort(500, 'permissions not propagated from project {} to sessions'.format(_id))


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
            hierarchy.propagate_changes(cont_name, _id, query, update)
        except APIStorageException:
            self.abort(500, 'tag change not propagated from group {}'.format(_id))


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

    def _build_zip_info(self, filepath):
        """
        Builds a json response containing member and comment info for a zipfile
        """
        with zipfile.ZipFile(filepath) as zf:
            info = {}
            info['comment'] = zf.comment
            info['members'] = []
            for zi in zf.infolist():
                m = {}
                m['path']      = zi.filename
                m['size']      = zi.file_size
                m['timestamp'] = datetime.datetime(*zi.date_time)
                m['comment']   = zi.comment

                info['members'].append(m)

            return info

    def get(self, cont_name, list_name, **kwargs):
        """
        .. http:get:: /api/(cont_name)/(cid)/files/(file_name)

            Gets the ticket used to download the file when the ticket is not provided.

            Downloads the file when the ticket is provided.

            :query ticket: should be empty

            :param cont_name: one of ``projects``, ``sessions``, ``acquisitions``, ``collections``
            :type cont_name: string

            :param cid: Container ID
            :type cid: string

            :statuscode 200: no error
            :statuscode 400: explain...
            :statuscode 409: explain...

            **Example request**:

            .. sourcecode:: http

                GET /api/acquisitions/57081d06b386a6dc79ca383c/files/fMRI%20Loc%20Word%20Face%20Obj.zip?ticket= HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {"ticket": "1e975e3d-21e9-41f4-bb97-261f03d35ba1"}

        """
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
        filepath = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))

        # Request for download ticket
        if self.get_param('ticket') == '':
            ticket = util.download_ticket(self.request.client_addr, 'file', _id, filename, fileinfo['size'], origin=self.origin)
            return {'ticket': config.db.downloads.insert_one(ticket).inserted_id}

        # Request for info about zipfile
        elif self.is_true('info'):
            try:
                info = self._build_zip_info(filepath)
            except zipfile.BadZipfile:
                self.abort(400, 'not a zip file')
            return info

        # Request to download zipfile member
        elif self.get_param('member') is not None:
            zip_member = self.get_param('member')
            try:
                with zipfile.ZipFile(filepath) as zf:
                    self.response.headers['Content-Type'] = util.guess_mimetype(zip_member)
                    self.response.write(zf.open(zip_member).read())
            except zipfile.BadZipfile:
                self.abort(400, 'not a zip file')
            except KeyError:
                self.abort(400, 'zip file contains no such member')
            # log download if we haven't already for this ticket
            if ticket:
                if not ticket.get('logged', False):
                    self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id)
                    config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
            else:
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id)

        # Authenticated or ticketed download request
        else:
            self.response.app_iter = open(filepath, 'rb')
            self.response.headers['Content-Length'] = str(fileinfo['size']) # must be set after setting app_iter
            if self.is_true('view'):
                self.response.headers['Content-Type'] = str(fileinfo.get('mimetype', 'application/octet-stream'))
            else:
                self.response.headers['Content-Type'] = 'application/octet-stream'
                self.response.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'

            # log download if we haven't already for this ticket
            if ticket:
                # recheck ticket for logged flag
                ticket = config.db.downloads.find_one({'_id': ticket_id})
                if not ticket.get('logged', False):
                    self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id)
                    config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
            else:
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id)


    @log_access(AccessType.view_file)
    def get_info(self, cont_name, list_name, **kwargs):
        return super(FileListHandler,self).get(cont_name, list_name, **kwargs)

    def post(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')

        # Ugly hack: ensure cont_name is singular. Pass singular or plural to code that expects it.
        if cont_name.endswith('s'):
            cont_name_plural = cont_name
            cont_name = cont_name[:-1]
        else:
            cont_name_plural = cont_name + 's'

        # Authorize
        permchecker, _, _, _, _ = self._initialize_request(cont_name_plural, list_name, _id)
        permchecker(noop)('POST', _id=_id)

        return upload.process_upload(self.request, upload.Strategy.targeted, container_type=cont_name, id_=_id, origin=self.origin)

    def put(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        permchecker, storage, mongo_validator, payload_validator, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        payload = self.request.json_body
        payload_validator(payload, 'PUT')
        if not set(payload.keys()).issubset({'info', 'modality', 'classification'}):
            self.abort(400, 'Can only update info, modality an classification keys on file.')

        classification = payload.get('classification')
        if classification:
            modality = payload.get('modality')
            if not modality:
                file_obj = storage.exec_op('GET', _id, query_params=kwargs)
                modality = file_obj.get('modality')

            if not ModalityHandler.check_classification(modality, classification):
                self.abort(400, 'Classification does not match allowable values for modality {}.'.format(modality))

        rf = self.is_true('replace_fields')

        try:
            keycheck(mongo_validator(permchecker(noop)))('PUT', _id=_id, query_params=kwargs, payload=payload)
            result = storage.update_file(_id, kwargs, payload, replace_fields=rf)
        except APIStorageException as e:
            self.abort(400, e.message)
        # abort if the query of the update wasn't able to find any matching documents
        if result.matched_count == 0:
            self.abort(404, 'Element not updated in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
        else:
            return {'modified':result.modified_count}

    def delete(self, cont_name, list_name, **kwargs):
        # Overriding base class delete to audit action before completion
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        permchecker(noop)('DELETE', _id=_id, query_params=kwargs)
        self.log_user_access(AccessType.delete_file, cont_name=cont_name, cont_id=_id)
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
        project = config.db['projects'].find_one({ '_id': bson.ObjectId(_id)})

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

class AnalysesHandler(ListHandler):

    def _check_ticket(self, ticket_id, _id, filename):
        ticket = config.db.downloads.find_one({'_id': ticket_id})
        if not ticket:
            self.abort(404, 'no such ticket')
        if ticket['ip'] != self.request.client_addr:
            self.abort(400, 'ticket not for this source IP')
        if not filename:
            return self._check_ticket_for_batch(ticket)
        if ticket.get('filename') != filename or ticket['target'] != _id:
            self.abort(400, 'ticket not for this resource')
        return ticket

    def _check_ticket_for_batch(self, ticket):
        if ticket.get('type') != 'batch':
            self.abort(400, 'ticket not for this resource')
        return ticket

    def put(self, *args, **kwargs):
        raise NotImplementedError("an analysis can't be modified")

    def post(self, cont_name, list_name, **kwargs):
        """
        Default behavior:
            Creates an analysis object and uploads supplied input
            and output files.
        When param ``job`` is true:
            Creates an analysis object and job object that reference
            each other via ``job`` and ``destination`` fields. Job based
            analyses are only allowed at the session level.
        """
        _id = kwargs.pop('cid')
        permchecker, storage, _, payload_validator, _ = self._initialize_request(cont_name, list_name, _id)
        permchecker(noop)('POST', _id=_id)

        if self.is_true('job'):
            if cont_name == 'sessions':
                payload = self.request.json_body
                payload_validator(payload.get('analysis',{}), 'POST')
                analysis = payload.get('analysis')
                job = payload.get('job')
                if job is None or analysis is None:
                    self.abort(400, 'JSON body must contain map for "analysis" and "job"')
                result = storage.create_job_and_analysis(cont_name, _id, analysis, job, self.origin)
                return {'_id': result['analysis']['_id']}
            else:
                self.abort(400, 'Analysis created via a job must be at the session level')

        payload = upload.process_upload(self.request, upload.Strategy.analysis, origin=self.origin)
        analysis = storage.default_analysis(self.origin)
        analysis.update(payload)
        result = storage.exec_op('POST', _id=_id, payload=analysis)
        if result.modified_count == 1:
            return {'_id': analysis['_id']}
        else:
            self.abort(500, 'Element not added in list analyses of container {} {}'.format(cont_name, _id))


    def download(self, cont_name, list_name, **kwargs):
        """
        .. http:get:: /api/(cont_name)/(cid)/analyses/(analysis_id)/files/(file_name)

            Download a file from an analysis or download a tar of all files

            When no filename is provided, a tar of all input and output files is created.
            The first request to this endpoint without a ticket ID generates a download ticket.
            A request to this endpoint with a ticket ID downloads the file(s).
            If the analysis object is tied to a job, the input file(s) are inlfated from
            the job's ``input`` array.

            :param cont_name: one of ``projects``, ``sessions``, ``collections``
            :type cont_name: string

            :param cid: Container ID
            :type cid: string

            :param analysis_id: Analysis ID
            :type analysis_id: string

            :param filename: (Optional) Filename of specific file to download
            :type cid: string

            :query string ticket: Download ticket ID

            :statuscode 200: no error
            :statuscode 404: No files on analysis ``analysis_id``
            :statuscode 404: Could not find file ``filename`` on analysis ``analysis_id``

            **Example request without ticket ID**:

            .. sourcecode:: http

                GET /api/sessions/57081d06b386a6dc79ca383c/analyses/5751cd3781460100a66405c8/files HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {
                  "ticket": "57f2af23-a94c-426d-8521-11b2e8782020",
                  "filename": "analysis_5751cd3781460100a66405c8.tar",
                  "file_cnt": 3,
                  "size": 4525137
                }

            **Example request with ticket ID**:

            .. sourcecode:: http

                GET /api/sessions/57081d06b386a6dc79ca383c/analyses/5751cd3781460100a66405c8/files?ticket=57f2af23-a94c-426d-8521-11b2e8782020 HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/octet-stream
                Content-Disposition: attachment; filename=analysis_5751cd3781460100a66405c8.tar;

            **Example Request with filename**:

            .. sourcecode:: http

                GET /api/sessions/57081d06b386a6dc79ca383c/analyses/5751cd3781460100a66405c8/files/exampledicom.zip?ticket= HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {
                  "ticket": "57f2af23-a94c-426d-8521-11b2e8782020",
                  "filename": "exampledicom.zip",
                  "file_cnt": 1,
                  "size": 4525137
                }


        """
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, _ = self._initialize_request(cont_name, list_name, _id)
        filename = kwargs.get('name')
        ticket_id = self.get_param('ticket')
        if ticket_id is None:
            permchecker(noop)('GET', _id=_id)
        elif ticket_id != '':
            ticket = self._check_ticket(ticket_id, _id, filename)
            if not self.origin.get('id'):
                self.origin = ticket.get('origin')
        analysis_id = kwargs.get('_id')
        fileinfo = storage.get_fileinfo(_id, analysis_id, filename)
        if fileinfo is None:
            error_msg = 'No files on analysis {}'.format(analysis_id)
            if filename:
                error_msg = 'Could not find file {} on analysis {}'.format(filename, analysis_id)
            self.abort(404, error_msg)
        if ticket_id == '':
            if filename:
                total_size = fileinfo[0]['size']
                file_cnt = 1
                ticket = util.download_ticket(self.request.client_addr, 'file', _id, filename, total_size, origin=self.origin)
            else:
                targets, total_size, file_cnt = self._prepare_batch(fileinfo)
                filename = 'analysis_' + analysis_id + '.tar'
                ticket = util.download_ticket(self.request.client_addr, 'batch', targets, filename, total_size, origin=self.origin)
            return {
                'ticket': config.db.downloads.insert_one(ticket).inserted_id,
                'size': total_size,
                'file_cnt': file_cnt,
                'filename': filename
            }
        else:
            if not filename:
                self._send_batch(ticket)
            elif not fileinfo:
                self.abort(404, '{} doesn''t exist'.format(filename))
            else:
                fileinfo = fileinfo[0]
                filepath = os.path.join(
                    config.get_item('persistent', 'data_path'),
                    util.path_from_hash(fileinfo['hash'])
                )
                filename = fileinfo['name']
                self.response.app_iter = open(filepath, 'rb')
                self.response.headers['Content-Length'] = str(fileinfo['size']) # must be set after setting app_iter
                if self.is_true('view'):
                    self.response.headers['Content-Type'] = str(fileinfo.get('mimetype', 'application/octet-stream'))
                else:
                    self.response.headers['Content-Type'] = 'application/octet-stream'
                    self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(filename)

            # log download if we haven't already for this ticket
            if ticket:
                ticket = config.db.downloads.find_one({'_id': ticket_id})
                if not ticket.get('logged', False):
                    self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id)
                    config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
            else:
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=_id)

    @log_access(AccessType.delete_analysis)
    def delete(self, cont_name, list_name, **kwargs):
        # Overriding base class delete to audit action before completion
        _id = kwargs.pop('cid')
        permchecker, storage, _, _, keycheck = self._initialize_request(cont_name, list_name, _id, query_params=kwargs)

        permchecker(noop)('DELETE', _id=_id, query_params=kwargs)
        self.log_user_access(AccessType.delete_file, cont_name=cont_name, cont_id=_id)
        try:
            result = keycheck(storage.exec_op)('DELETE', _id, query_params=kwargs)
        except APIStorageException as e:
            self.abort(400, e.message)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Element not removed from list {} in container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def _prepare_batch(self, fileinfo):
        ## duplicated code from download.py
        ## we need a way to avoid this
        targets = []
        total_size = total_cnt = 0
        data_path = config.get_item('persistent', 'data_path')
        for f in fileinfo:
            filepath = os.path.join(data_path, util.path_from_hash(f['hash']))
            if os.path.exists(filepath): # silently skip missing files
                targets.append((filepath, 'analyses/' + f['name'], f['size']))
                total_size += f['size']
                total_cnt += 1
        return targets, total_size, total_cnt

    def _send_batch(self, ticket):
        self.response.app_iter = download.archivestream(ticket)
        self.response.headers['Content-Type'] = 'application/octet-stream'
        self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(ticket['filename'])

    def delete_note(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        analysis_id = kwargs.pop('_id')
        permchecker, storage, _, _, _ = self._initialize_request(cont_name, list_name, _id)
        note_id = kwargs.get('note_id')
        permchecker(noop)('DELETE', _id=_id)
        result = storage.delete_note(_id=_id, analysis_id=analysis_id, note_id=note_id)
        if result.modified_count == 1:
            return {'modified':result.modified_count}
        else:
            self.abort(404, 'Element not removed from list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))

    def add_note(self, cont_name, list_name, **kwargs):
        _id = kwargs.pop('cid')
        analysis_id = kwargs.get('_id')
        permchecker, storage, _, _, _ = self._initialize_request(cont_name, list_name, _id)
        payload = self.request.json_body

        notes_schema_file = list_handler_configurations[cont_name]['notes']['storage_schema_file']
        input_schema_uri = validators.schema_uri('input', notes_schema_file)
        input_validator = validators.from_schema_path(input_schema_uri)
        input_validator(payload, 'POST')

        payload['_id'] = str(bson.objectid.ObjectId())
        payload['user'] = payload.get('user', self.uid)
        payload['created'] = datetime.datetime.utcnow()
        permchecker(noop)('POST', _id=_id)
        result = storage.add_note(_id=_id, analysis_id=analysis_id, payload=payload)
        if result.modified_count == 1:
            return {'modified':result.modified_count}
        else:
            self.abort(404, 'Element not added in list {} of container {} {}'.format(storage.list_name, storage.cont_name, _id))
