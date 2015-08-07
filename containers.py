# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
log = logging.getLogger('scitran.api')

import os
import cgi
import bson
import json
import shutil
import zipfile
import datetime
import jsonschema

import tempdir as tempfile

import base
import util
import users


FILE_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'File',
    'type': 'object',
    'properties': {
        'name': {
            'title': 'Name',
            'type': 'string',
        },
        'ext': {
            'title': 'Extension',
            'type': 'string',
        },
        'filesize': {
            'title': 'Size',
            'type': 'integer',
        },
        'sha1': {
            'title': 'SHA-1',
            'type': 'string',
        },
        'type': {
            'title': 'Type',
            'type': 'string',
        },
        'kinds': {
            'title': 'Kinds',
            'type': 'array',
        },
        'state': {
            'title': 'State',
            'type': 'array',
        },
    },
    'required': ['name', 'ext', 'filesize', 'sha1', 'type', 'kinds', 'state'],
    'additionalProperties': False
}

FILE_UPLOAD_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Upload',
    'type': 'object',
    'properties': {
        'files': {
            'title': 'Files',
            'type': 'array',
            'items': FILE_SCHEMA,
            'uniqueItems': True,
        },
    },
    'required': ['files'],
    'additionalProperties': False,
}

FILE_ACCESS_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'File Download',
    'anyOf': [
        {
            'type': 'object',
            'properties': {
                'type': {
                    'title': 'Type',
                    'type': 'string',
                },
                'kinds': {
                    'title': 'Kinds',
                    'type': 'array',
                },
                'state': {
                    'title': 'State',
                    'type': 'array',
                },
            },
            'required': ['type', 'kinds', 'state'],
        },
        {
            'type': 'object',
            'properties': {
                'name': {
                    'title': 'Type',
                    'type': 'string',
                },
                'ext': {
                    'title': 'Type',
                    'type': 'string',
                },
            },
            'required': ['name'],
        },
    ],
}


class ContainerList(base.RequestHandler):

    def _post(self):
        try:
            json_body = self.request.json_body
            jsonschema.validate(json_body, self.post_schema)
        except (ValueError, jsonschema.ValidationError) as e:
            self.abort(400, str(e))
        return json_body

    def _get(self, query, projection, admin_only=False, uid=None):
        projection = {p: 1 for p in projection + ['files']}
        if self.public_request:
            query['public'] = True
        else:
            if uid is not None:
                if uid != self.uid and not self.superuser_request:
                    self.abort(403, 'User ' + self.uid + ' may not see the Projects of User ' + uid)
            if not self.superuser_request or uid:
                if admin_only:
                    query['permissions'] = {'$elemMatch': {'_id': uid or self.uid, 'site': self.source_site, 'access': 'admin'}}
                else:
                    query['permissions'] = {'$elemMatch': {'_id': uid or self.uid, 'site': self.source_site}}
            projection['permissions'] = {'$elemMatch': {'_id': uid or self.uid, 'site': self.source_site}}
        containers = list(self.dbc.find(query, projection))
        for container in containers:
            container['_id'] = str(container['_id'])
            container.setdefault('timestamp', datetime.datetime.utcnow())
            container['timestamp'], container['timezone'] = util.format_timestamp(container['timestamp'], container.get('timezone')) # TODO json serializer should do this
            container['attachment_count'] = len([f for f in container.get('files', []) if f.get('flavor') == 'attachment'])
        return containers


class Container(base.RequestHandler):

    def _get(self, _id, min_role=None, filename=None, perm_only=False, dbc=None, dbc_name=None):
        dbc = dbc or self.dbc
        dbc_name = dbc_name or self.__class__.__name__
        container = dbc.find_one({'_id': _id}, ['permissions'] if perm_only else None)
        if not container:
            self.abort(404, 'no such ' + dbc_name)
        user_perm = util.user_perm(container['permissions'], self.uid, self.source_site)
        if self.public_request:
            ticket_id = self.request.GET.get('ticket')
            if ticket_id:
                ticket = self.app.db.downloads.find_one({'_id': ticket_id})
                if not ticket:
                    self.abort(404, 'no such ticket')
                if ticket['target'] != _id or ticket['filename'] != filename or ticket['ip'] != self.request.client_addr:
                    self.abort(400, 'ticket not for this resource or source IP')
            elif not container.get('public', False):
                self.abort(403, 'this ' + dbc_name + ' is not public')
            del container['permissions']
        elif not self.superuser_request:
            if not user_perm:
                self.abort(403, self.uid + ' does not have permissions on this ' + dbc_name)
            if min_role and users.INTEGER_ROLES[user_perm['access']] < users.INTEGER_ROLES[min_role]:
                self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this ' + dbc_name)
            if user_perm['access'] != 'admin': # if not admin, mask permissions of other users
                container['permissions'] = [user_perm]
        if self.request.GET.get('paths', '').lower() in ('1', 'true'):
            for fileinfo in container['files']:
                fileinfo['path'] = str(_id)[-3:] + '/' + str(_id) + '/' + fileinfo['filename']
        container['_id'] = str(container['_id'])
        container.setdefault('timestamp', datetime.datetime.utcnow())
        container['timestamp'], container['timezone'] = util.format_timestamp(container['timestamp'], container.get('timezone')) # TODO json serializer should do this
        for note in container.get('notes', []):
            note['timestamp'], _ = util.format_timestamp(note['timestamp']) # TODO json serializer should do this
        return container, user_perm

    def _put(self, _id):
        json_body = self.validate_json_body(['project'])
        self._get(_id, 'admin' if 'permissions' in json_body else 'rw', perm_only=True)
        self.update_db(_id, json_body)
        return json_body

    def _delete(self, _id):
        self.dbc.delete_one({'_id': _id})
        container_path = os.path.join(self.app.config['data_path'], str(_id)[-3:] + '/' + str(_id))
        if os.path.isdir(container_path):
            log.debug('deleting ' + container_path)
            shutil.rmtree(container_path)

    def validate_json_body(self, oid_keys=[]):
        try:
            json_body = self.request.json_body
            jsonschema.validate(json_body, self.put_schema)
        except (ValueError, jsonschema.ValidationError) as e:
            self.abort(400, str(e))
        if 'permissions' in json_body and json_body['permissions'] is None:
            json_body.pop('permissions')
        for key in oid_keys:
            if key in json_body:
                json_body[key] = bson.ObjectId(json_body[key])
        return json_body

    def update_db(self, _id, json_body):
        for note in json_body.get('notes', []):
            note.setdefault('author', self.uid)
            if 'timestamp' in note:
                note['timestamp'] = util.parse_timestamp(note['timestamp'])
            else:
                note['timestamp'] = datetime.datetime.utcnow()
        self.dbc.update({'_id': _id}, {'$set': util.mongo_dict(json_body)})

    def file(self, cid, filename=None):
        _id = bson.ObjectId(cid)
        if self.request.method == 'GET':
            container, _ = self._get(_id, 'ro', filename)
            return self._get_file(_id, container, filename)
        elif self.request.method == 'DELETE':
            container, _ = self._get(_id, 'rw', filename)
            return self._delete_file(_id, container, filename)
        elif self.request.method == 'PUT':
            container, _ = self._get(_id, 'rw', filename)
            return self._put_file(_id, container, filename)
        elif self.request.method == 'POST':
            container, _ = self._get(_id, 'rw', filename)
            return self._post_file(_id, container, filename)
        else:
            self.abort(405)

    def _get_file(self, _id, container, filename):
        """Download one file."""
        fileinfo = util.container_fileinfo(container, filename)
        if not fileinfo:
            self.abort(404, 'no such file')
        hash_ = self.request.GET.get('hash')
        if hash_ and hash_ != fileinfo['hash']:
            self.abort(409, 'file exists, hash mismatch')
        filepath = os.path.join(self.app.config['data_path'], str(_id)[-3:] + '/' + str(_id), filename)
        if self.request.GET.get('ticket') == '':    # request for download ticket
            ticket = util.download_ticket(self.request.client_addr, 'file', _id, filename, fileinfo['filesize'])
            return {'ticket': self.app.db.downloads.insert(ticket)}
        else:                                       # authenticated or ticketed (unauthenticated) download
            zip_member = self.request.GET.get('member')
            if self.request.GET.get('info', '').lower() in ('1', 'true'):
                try:
                    with zipfile.ZipFile(filepath) as zf:
                        return [(zi.filename, zi.file_size, util.format_timestamp(datetime.datetime(*zi.date_time))[0]) for zi in zf.infolist()]
                except zipfile.BadZipfile:
                    self.abort(400, 'not a zip file')
            elif self.request.GET.get('comment', '').lower() in ('1', 'true'):
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
                self.response.headers['Content-Length'] = str(fileinfo['filesize']) # must be set after setting app_iter
                if self.request.GET.get('view', '').lower() in ('1', 'true'):
                    self.response.headers['Content-Type'] = str(fileinfo.get('mimetype', 'application/octet-stream'))
                else:
                    self.response.headers['Content-Type'] = 'application/octet-stream'
                    self.response.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'

    def _delete_file(self, _id, container, filename):
        """Delete one file."""
        fileinfo = util.container_fileinfo(container, filename)
        if not fileinfo:
            self.abort(404, 'no such file')
        filepath = os.path.join(self.app.config['data_path'], str(_id)[-3:] + '/' + str(_id), filename)
        r = self.dbc.update_one({'_id': _id}, {'$pull': {'files': {'filename': filename}}})
        if r.modified_count != 1:
            self.abort(400) # FIXME need better error checking
        if os.path.exists(filepath):
            os.remove(filepath)
            log.info('removed file ' + filepath)
        else:
            log.warning(filepath + ' does not exist')

    def _put_file(self, _id, container, filename):
        """Update file metadata."""
        fileinfo = util.container_fileinfo(container, filename)
        if not fileinfo:
            self.abort(404, 'no such file')
        # TODO: implement file metadata updates
        self.abort(400, 'PUT is not yet implemented')

    def _post_file(self, _id, container, filename):
        """Upload one file."""
        tags = []
        metadata = {}
        if self.request.content_type == 'multipart/form-data':
            filestream = None
            # use cgi lib to parse multipart data without loading all into memory; use tempfile instead
            # FIXME avoid using tempfile; processs incoming stream on the fly
            fs_environ = self.request.environ.copy()
            fs_environ.setdefault('CONTENT_LENGTH', '0')
            fs_environ['QUERY_STRING'] = ''
            form = cgi.FieldStorage(fp=self.request.body_file, environ=fs_environ, keep_blank_values=True)
            for fieldname in form:
                field = form[fieldname]
                if fieldname == 'file':
                    filestream = field.file
                    filename = field.filename
                elif fieldname == 'tags':
                    try:
                        tags = json.loads(field.value)
                    except ValueError:
                        self.abort(400, 'non-JSON value in "tags" parameter')
                elif fieldname == 'metadata':
                    try:
                        metadata = json.loads(field.value)
                    except ValueError:
                        self.abort(400, 'non-JSON value in "metadata" parameter')
            if filestream is None:
                self.abort(400, 'multipart/form-data must contain a "file" field')
        elif filename is None:
            self.abort(400, 'Request must contain a filename parameter.')
        else:
            if 'Content-MD5' not in self.request.headers:
                self.abort(400, 'Request must contain a valid "Content-MD5" header.')
            try:
                tags = json.loads(self.request.GET.get('tags', '[]'))
            except ValueError:
                self.abort(400, 'invalid "tags" parameter')
            try:
                metadata = json.loads(self.request.GET.get('metadata', '{}'))
            except ValueError:
                self.abort(400, 'invalid "metadata" parameter')
            filestream = self.request.body_file
        flavor = self.request.GET.get('flavor', 'data') # TODO: flavor should go away
        if flavor not in ['data', 'attachment']:
            self.abort(400, 'Query must contain flavor parameter: "data" or "attachment".')

        with tempfile.TemporaryDirectory(prefix='.tmp', dir=self.app.config['upload_path']) as tempdir_path:
            filepath = os.path.join(tempdir_path, filename)
            md5 = self.request.headers.get('Content-MD5')
            success, digest, _, duration = util.receive_stream_and_validate(filestream, filepath, md5)

            if not success:
                self.abort(400, 'Content-MD5 mismatch.')
            filesize = os.path.getsize(filepath)
            mimetype = util.guess_mimetype(filepath)
            filetype = util.guess_filetype(filepath, mimetype)
            datainfo = {
                    'fileinfo': {
                        'filename': filename,
                        'filesize': filesize,
                        'filehash': digest,
                        'filetype': filetype,
                        'flavor': flavor,
                        'mimetype': mimetype,
                        'tags': tags,
                        'metadata': metadata,
                        },
                    }
            throughput = filesize / duration.total_seconds()
            log.info('Received    %s [%s, %s/s] from %s' % (filename, util.hrsize(filesize), util.hrsize(throughput), self.request.client_addr))
            force = self.request.GET.get('force', '').lower() in ('1', 'true')
            success = util.commit_file(self.dbc, _id, datainfo, filepath, self.app.config['data_path'], force)
            if success is None:
                self.abort(202, 'identical file exists')
            elif success == False:
                self.abort(409, 'file exists; use force to overwrite')
