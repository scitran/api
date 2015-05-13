# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
log = logging.getLogger('scitran.api')

import os
import json
import pytz
import hashlib
import jsonschema
import bson.json_util

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
        'size': {
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
    'required': ['name', 'ext', 'size', 'sha1', 'type', 'kinds', 'state'],
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

FILE_DOWNLOAD_SCHEMA = {
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
            'required': ['name', 'ext'],
        },
    ],
}


def fixup_timestamps(container):
    if 'timestamp' in container:
        container_timezone = pytz.timezone(container.get('timezone', None) or 'UTC')
        container['timestamp'] = container_timezone.localize(container['timestamp']).isoformat()
        container['timezone'] = container_timezone.zone


class ContainerList(base.RequestHandler):

    def _get(self, query, projection, admin_only=False):
        if self.public_request:
            query['public'] = True
        else:
            projection['permissions'] = {'$elemMatch': {'_id': self.uid, 'site': self.source_site}}
            if not self.superuser_request:
                if admin_only:
                    query['permissions'] = {'$elemMatch': {'_id': self.uid, 'site': self.source_site, 'access': 'admin'}}
                else:
                    query['permissions'] = {'$elemMatch': {'_id': self.uid, 'site': self.source_site}}
        containers = list(self.dbc.find(query, projection))
        for container in containers:
            container['_id'] = str(container['_id'])
            fixup_timestamps(container)
        return containers


class Container(base.RequestHandler):

    def _get(self, _id, min_role=None, perm_only=False, dbc=None, dbc_name=None):
        dbc = dbc or self.dbc
        dbc_name = dbc_name or self.__class__.__name__
        container = dbc.find_one({'_id': _id}, ['permissions'] if perm_only else None)
        if not container:
            self.abort(404, 'no such ' + dbc_name)
        user_perm = util.user_perm(container['permissions'], self.uid, self.source_site)
        if self.public_request:
            if not container.get('public', False):
                self.abort(403, 'this ' + dbc_name + 'is not public')
            del container['permissions']
        elif not self.superuser_request:
            if not user_perm:
                self.abort(403, self.uid + ' does not have permissions on this ' + dbc_name)
            if min_role and users.INTEGER_ROLES[user_perm['access']] < users.INTEGER_ROLES[min_role]:
                self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this ' + dbc_name)
            if user_perm['access'] != 'admin': # if not admin, mask permissions of other users
                container['permissions'] = [user_perm]
        if self.request.get('paths').lower() in ('1', 'true'):
            for file_info in container['files']:
                file_info['path'] = str(_id)[-3:] + '/' + str(_id) + '/' + file_info['name'] + file_info['ext']
        container['_id'] = str(container['_id'])
        fixup_timestamps(container)
        return container, user_perm

    def put(self, _id):
        json_body = self.validate_json_body(_id, ['project'])
        self._get(_id, 'admin' if 'permissions' in json_body else 'rw', perm_only=True)
        self.update_db(_id, json_body)
        return json_body

    def validate_json_body(self, _id, oid_keys=[]):
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
        self.dbc.update({'_id': _id}, {'$set': util.mongo_dict(json_body)})

    def get_file(self, cid):
        try:
            file_spec = self.request.json_body
            jsonschema.validate(file_spec, FILE_DOWNLOAD_SCHEMA)
        except (ValueError, jsonschema.ValidationError) as e:
            self.abort(400, str(e))
        _id = bson.ObjectId(cid)
        container, _ = self._get(_id, 'ro')
        for file_info in container['files']:
            if 'name' in file_spec:
                if file_info['name'] == file_spec['name'] and file_info['ext'] == file_spec['ext']:
                    break
            else:
                if file_info['type'] == file_spec['type'] and file_info['kinds'] == file_spec['kinds'] and file_info['state'] == file_spec['state']:
                    break
        else:
            self.abort(404, 'no such file')
        filename = file_info['name'] + file_info['ext']
        filepath = os.path.join(self.app.config['data_path'], str(_id)[-3:] + '/' + str(_id), filename)
        if self.request.method == 'GET':
            self.response.app_iter = open(filepath, 'rb')
            self.response.headers['Content-Length'] = str(file_info['size']) # must be set after setting app_iter
            self.response.headers['Content-Type'] = 'application/octet-stream'
            self.response.headers['Content-Disposition'] = 'attachment; filename=%s' % str(filename)
        else:
            ticket = util.download_ticket('single', filepath, filename, file_info['size'])
            tkt_id = self.app.db.downloads.insert(ticket)
            return {'url': self.uri_for('named_download', fn=filename, _scheme='https', ticket=tkt_id)}

    def _put(self, cid=None, flavor='file'):
        """
        Receive a targeted processor or user upload for an attachment or file.

        This PUT route is used to add a file to an existing container, not for creating new containers.
        This upload is different from the main PUT route, because this does not update the main container
        metadata, nor does it try to parse the file to determine sorting information. The uploaded file(s)
        will always get uploaded to the specificied container.

        Accepts a multipart request that contains the following form fields:
        - 'metadata': list of dicts, each dict contains metadata for a file
        - filename: file object
        - 'sha': list of dicts, each dict contains 'name' and 'sha1'.

        """
        # TODO read self.request.body, using '------WebKitFormBoundary' as divider
        # first line is 'content-disposition' line, extract filename
        # second line is content-type, determine how to write to a file, as bytes or as string
        # third linedata_path = self.app.config['data_path'], just a separator, useless
        def receive_stream_and_validate(stream, digest, filename):
            # FIXME pull this out to also be used from core.Core.put() and also replace the duplicated code below
            hash_ = hashlib.sha1()
            filepath = os.path.join(tempdir_path, filename)
            with open(filepath, 'wb') as fd:
                for chunk in iter(lambda: stream.read(2**20), ''):
                    hash_.update(chunk)
                    fd.write(chunk)
            if hash_.hexdigest() != digest:
                self.abort(400, 'Content-MD5 mismatch.')
            return filepath

        if self.request.content_type != 'multipart/form-data':
            self.abort(400, 'content-type must be "multipart/form-data"')
        # TODO: metadata validation
        _id = bson.ObjectId(cid)
        container, _ = self._get(_id, 'rw')
        data_path = self.app.config['data_path']
        quarantine_path = self.app.config['quarantine_path']
        hashes = []
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=self.app.config['data_path']) as tempdir_path:
            # get and hash the metadata
            metahash = hashlib.sha1()
            metastr = self.request.POST.get('metadata').file.read()  # returns a string?
            metadata = json.loads(metastr)
            metahash.update(metastr)
            hashes.append({'name': 'metadata', 'sha1': metahash.hexdigest()})

            sha1s = json.loads(self.request.POST.get('sha').file.read())
            for finfo in metadata:
                fname = finfo.get('name') + finfo.get('ext')  # finfo['ext'] will always be empty
                fhash = hashlib.sha1()
                fobj = self.request.POST.get(fname).file
                filepath = os.path.join(tempdir_path, fname)
                with open(filepath, 'wb') as fd:
                    for chunk in iter(lambda: fobj.read(2**20), ''):
                        fhash.update(chunk)
                        fd.write(chunk)
                for s in sha1s:
                    if fname == s.get('name'):
                        if fhash.hexdigest() != s.get('sha1'):
                            self.abort(400, 'Content-MD5 mismatch %s vs %s' % (fhash.hexdigest(), s.get('sha1')))
                        else:
                            finfo['sha1'] = s.get('sha1')
                            status, detail = util.insert_file(self.dbc, _id, finfo, filepath, s.get('sha1'), data_path, quarantine_path, flavor=flavor)
                        if status != 200:
                            self.abort(400, 'upload failed')
                        break
                else:
                    self.abort(400, '%s is not listed in the sha1s' % fname)

    def _fdm_put(self, cid=None, flavor='file'):
        """
        Receive a targeted processor or user upload for an attachment or file.

        This PUT route is used to add a file to an existing container, not for creating new containers.
        This upload is different from the main PUT route, because this does not update the main container
        metadata, nor does it try to parse the file to determine sorting information. The uploaded file(s)
        will always get uploaded to the specificied container.

        Accepts a multipart request that uploads each file to an array form field 'file'.

        Example uploading one file:

          ------WebKitFormBoundaryAVH8u1QBLfm51vbT
          Content-Disposition: form-data; name="file[0]"; filename="someFile.png"
          Content-Type: image/png

          ------WebKitFormBoundaryAVH8u1QBLfm51vbT--

        Example uploading multiple files:

          ------WebKitFormBoundarylC41xBs7QiJ85YEX
          Content-Disposition: form-data; name="file[0]"; filename="anotherFile.jpg"
          Content-Type: image/jpeg

          ------WebKitFormBoundarylC41xBs7QiJ85YEX
          Content-Disposition: form-data; name="file[1]"; filename="aYetThirdFile.png"
          Content-Type: image/png

          ------WebKitFormBoundarylC41xBs7QiJ85YEX--

        """

        if self.request.content_type != 'multipart/form-data':
            self.abort(400, 'content-type must be "multipart/form-data"')

        # TODO: metadata validation
        _id = bson.ObjectId(cid)
        container, _ = self._get(_id, 'rw')
        data_path = self.app.config['data_path']
        quarantine_path = self.app.config['quarantine_path']

        with tempfile.TemporaryDirectory(prefix='.tmp', dir=self.app.config['data_path']) as tempdir_path:
            # metadata = json.loads(self.request.POST.get('metadata'))

            # Process one, or many files
            for fieldName, fieldContent in self.request.POST.items():

                # If this is a file field
                if fieldName.startswith('file'):
                    fobj = fieldContent.file
                    filename = fieldContent.filename
                    filepath = os.path.join(tempdir_path, filename)

                    log.info('Adding ' + filename + ' to ' + cid)

                    # Save and hash the file
                    fhash = hashlib.sha1()
                    with open(filepath, 'wb') as fd:
                        for chunk in iter(lambda: fobj.read(2**20), ''):
                            fhash.update(chunk)
                            fd.write(chunk)

                    expectedHash = 'pants'
                    actualHash = fhash.hexdigest()

                    if expectedHash != actualHash:
                        log.info('HASH MISMATCH %s vs %s' % (expectedHash, actualHash))

                    fn, ext = os.path.splitext(filename)
                    info = dict(
                        name=fn,
                        ext=ext,
                        size=os.path.getsize(filepath),
                        sha1=actualHash,
                    )

                    # Attach file to object
                    status, detail = util.insert_file(self.dbc, _id, info, filepath, actualHash, data_path, quarantine_path, flavor=flavor)

                    if status != 200:
                        self.abort(400, 'upload failed')

    def put_file(self, cid=None):
        """Receive a targeted upload of a dataset file."""
        if self.request.get('fdm').lower() in ('1', 'true'):
            self._fdm_put(cid, flavor='file')
        else:
            self._put(cid, flavor='file')

    def put_attachment(self, cid):
        """Recieve a targetted upload of an attachment file."""
        if self.request.get('fdm').lower() in ('1', 'true'):
            self._fdm_put(cid, flavor='attachment')
        else:
            self._put(cid, flavor='attachment')

    def get_tile(self, cid):
        """fetch info about a tiled tiff, or retrieve a specific tile."""
        _id = bson.ObjectId(cid)
        container, _ = self._get(_id, 'ro')  # need at least read access to view tiles
        montage_info = None
        for f in container.get('files'):
            if f['kinds'] == ['montage'] and f['ext'] == '.zip':
                montage_info = f
                break
        if not montage_info:
            self.abort(404, 'montage zip not found')
        fn = montage_info['name'] + montage_info['ext']
        fp = os.path.join(self.app.config['data_path'], cid[-3:], cid, fn)
        z = self.request.get('z')
        x = self.request.get('x')
        y = self.request.get('y')
        if not (z and x and y):
            return util.get_info(fp)
        else:
            self.response.content_type = 'image/jpeg'
            tile = util.get_tile(fp, int(z), int(x), int(y))
            if tile:
                self.response.write(tile)

    def get_attachment(self, cid):
        """Download one attachment."""
        fname = self.request.get('name')
        _id = bson.ObjectId(cid)
        container, _ = self._get(_id, 'ro')
        fpath = os.path.join(self.app.config['data_path'], str(_id)[-3:] + '/' + str(_id), fname)
        for a_info in container['attachments']:
            if (a_info['name'] + a_info['ext']) == fname:
                break
        else:
            self.abort(404, 'no such file')
        if self.request.method == 'GET':
            self.response.app_iter = open(fpath, 'rb')
            self.response.headers['Content-Length'] = str(a_info['size']) # must be set after setting app_iter
            self.response.headers['Content-Type'] = 'application/octet-stream'
        else:
            ticket = util.download_ticket('single', fpath, fname, a_info['size'])
            tkt_id = self.app.db.downloads.insert(ticket)
            return {'url': self.uri_for('named_download', fn=fname, _scheme='https', ticket=tkt_id)}

    def delete_attachment(self, cid):
        """Delete one attachment."""
        fname = self.request.get('name')
        _id = bson.ObjectId(cid)
        container, _ = self._get(_id, 'rw')
        fpath = os.path.join(self.app.config['data_path'], str(_id)[-3:] + '/' + str(_id), fname)
        for a_info in container['attachments']:
            if (a_info['name'] + a_info['ext']) == fname:
                break
        else:
            self.abort(404, 'no such file')

        name, ext = os.path.splitext(fname)
        success = self.dbc.update({'_id': _id, 'attachments.name': fname}, {'$pull': {'attachments': {'name': fname}}})
        if not success['updatedExisting']:
            log.info('could not remove database entry.')
        if os.path.exists(fpath):
            os.remove(fpath)
            log.info('removed file %s' % fpath)
        else:
            log.info('could not remove file, file %s does not exist' % fpath)
