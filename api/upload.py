import bson
import datetime
import json
import os.path
import shutil

from . import base
from . import config
from . import files
from .jobs import rules
from . import tempdir as tempfile
from . import placer as pl
from . import util
from . import validators

from .dao import hierarchy, APIStorageException
from .dao import noop


log = config.log

Strategy = util.Enum('Strategy', {
    'targeted'   : pl.TargetedPlacer,   # Upload N files to a container.
    'engine'     : pl.EnginePlacer,     # Upload N files from the result of a successful job.
    'token'      : pl.TokenPlacer,      # Upload N files to a saved folder based on a token.
    'packfile'   : pl.PackfilePlacer,   # Upload N files as a new packfile to a container.
    'labelupload': pl.LabelPlacer,
    'uidupload'  : pl.UIDPlacer,
    'analysis' : pl.AnalysisPlacer    # Upload N files for an analysys (no db updates)
})

def process_upload(request, strategy, container_type=None, id=None, origin=None, context=None, response=None, metadata=None):
    """
    Universal file upload entrypoint.

    Format:
        Multipart form upload with N file fields, each with their desired filename.
        For technical reasons, no form field names can be repeated. Instead, use (file1, file2) and so forth.

        Depending on the type of upload, a non-file form field called "metadata" may/must also be sent.
        If present, it is expected to be a JSON string matching the schema for the upload strategy.

        Currently, the JSON returned may vary by strategy.

        Some examples:
        curl -F file1=@science.png   -F file2=@rules.png url
        curl -F metadata=<stuff.json -F file=@data.zip   url
        http --form POST url metadata=@stuff.json file@data.zip

    Features:
                                               | targeted |  reaper   | engine | packfile
        Must specify a target container        |     X    |           |    X   |
        May create hierarchy on demand         |          |     X     |        |     X

        May  send metadata about the files     |     X    |     X     |    X   |     X
        MUST send metadata about the files     |          |     X     |        |     X

        Creates a packfile from uploaded files |          |           |        |     X
    """

    if not isinstance(strategy, Strategy):
        raise Exception('Unknown upload strategy')

    if id is not None and container_type == None:
        raise Exception('Unspecified container type')

    if container_type is not None and container_type not in ('acquisition', 'session', 'project', 'collection'):
        raise Exception('Unknown container type')

    timestamp = datetime.datetime.utcnow()

    container = None
    if container_type and id:
        container = hierarchy.get_container(container_type, id)

    # The vast majority of this function's wall-clock time is spent here.
    # Tempdir is deleted off disk once out of scope, so let's hold onto this reference.
    form, tempdir = files.process_form(request)

    if 'metadata' in form:
        try:
            metadata = json.loads(form['metadata'].value)
        except Exception:
            raise files.FileStoreException('wrong format for field "metadata"')

    placer_class = strategy.value
    placer = placer_class(container_type, container, id, metadata, timestamp, origin, context)
    placer.check()

    # Browsers, when sending a multipart upload, will send files with field name "file" (if sinuglar)
    # or "file1", "file2", etc (if multiple). Following this convention is probably a good idea.
    # Here, we accept any
    file_fields = filter(lambda x: form[x].filename is not None, form)

    # TODO: Change schemas to enabled targeted uploads of more than one file.
    # Ref docs from placer.TargetedPlacer for details.
    if strategy == Strategy.targeted and len(file_fields) > 1:
        raise Exception("Targeted uploads can only send one file")

    for field in file_fields:
        field = form[field]

        # Augment the cgi.FieldStorage with a variety of custom fields.
        # Not the best practice. Open to improvements.
        # These are presumbed to be required by every function later called with field as a parameter.
        field.path	 = os.path.join(tempdir.name, field.filename)
        field.size	 = os.path.getsize(field.path)
        field.hash	 = field.file.get_formatted_hash()
        field.mimetype = util.guess_mimetype(field.filename) # TODO: does not honor metadata's mime type if any
        field.modified = timestamp

        # create a file-info map commonly used elsewhere in the codebase.
        # Stands in for a dedicated object... for now.
        info = {
            'name':	 field.filename,
            'modified': field.modified, #
            'size':	 field.size,
            'mimetype': field.mimetype,
            'hash':	 field.hash,
            'origin': origin,

            'type': None,
            'instrument': None,
            'measurements': [],
            'tags': [],
            'metadata': {}
        }

        placer.process_file_field(field, info)

    # Respond either with Server-Sent Events or a standard json map
    if placer.sse and not response:
        raise Exception("Programmer error: response required")
    elif placer.sse:
        log.debug('SSE')
        response.headers['Content-Type'] = 'text/event-stream; charset=utf-8'
        response.headers['Connection']   = 'keep-alive'
        response.app_iter = placer.finalize()
    else:
        return placer.finalize()


class Upload(base.RequestHandler):

    def reaper(self):
        """Receive a sortable reaper upload."""
        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            try:
                file_store = files.FileStore(self.request, tempdir_path)
            except files.FileStoreException as e:
                self.abort(400, str(e))
            now = datetime.datetime.utcnow()
            fileinfo = dict(
                name=file_store.filename,
                created=now,
                modified=now,
                size=file_store.size,
                hash=file_store.hash,
                mimetype=util.guess_mimetype(file_store.filename),
                tags=file_store.tags,
                metadata=file_store.metadata.get('file', {}).get('metadata', {}),
                origin=self.origin
            )

            target, file_metadata = hierarchy.create_container_hierarchy(file_store.metadata)
            fileinfo.update(file_metadata)
            f = target.find(file_store.filename)
            target_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
            if not f:
                file_store.move_file(target_path)
                target.add_file(fileinfo)
                rules.create_jobs(config.db, target.container, target.level[:-1], fileinfo)
            elif not files.identical(file_store.hash, file_store.path, f['hash'], util.path_from_hash(f['hash'])):
                file_store.move_file(target_path)
                target.update_file(fileinfo)
                rules.create_jobs(config.db, target.container, target.level[:-1], fileinfo)
            throughput = file_store.size / file_store.duration.total_seconds()
            log.info('Received    %s [%s, %s/s] from %s' % (file_store.filename, util.hrsize(file_store.size), util.hrsize(throughput), self.request.client_addr))

    def upload(self, strategy):
        """
        .. http:post:: /api/upload/<strategy:label|uid>

            Receive a sortable reaper upload.

            :statuscode 402: no error
            :statuscode 500: no error
        """

        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')

        # TODO: what enum
        if strategy == 'label':
            strategy = Strategy.labelupload
        elif strategy == 'uid':
            strategy = Strategy.uidupload
        else:
            self.abort(500, 'stragegy {} not implemented'.format(strategy))
        return process_upload(self.request, strategy, origin=self.origin)

    def engine(self):
        """
        .. http:post:: /api/engine

            Confirm endpoint is ready for requests

            :query level: container_type
            :query id: container_id
            :query job: job_id

            :statuscode 400: describe me
            :statuscode 402: describe me
            :statuscode 404: describe me
        """

        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')

        level = self.get_param('level')
        if level is None:
            self.abort(404, 'container level is required')

        if level != 'acquisition':
            self.abort(404, 'engine uploads are supported only at the acquisition level')

        acquisition_id = self.get_param('id')
        if not acquisition_id:
            self.abort(404, 'container id is required')
        else:
            acquisition_id = bson.ObjectId(acquisition_id)
        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            try:
                file_store = files.MultiFileStore(self.request, tempdir_path)
            except files.FileStoreException as e:
                self.abort(400, str(e))
            if not file_store.metadata:
                self.abort(400, 'metadata is missing')
            payload_schema_uri = util.schema_uri('input', 'enginemetadata.json')
            metadata_validator = validators.from_schema_path(payload_schema_uri)
            metadata_validator(file_store.metadata, 'POST')
            file_infos = file_store.metadata['acquisition'].pop('files', [])
            now = datetime.datetime.utcnow()
            try:
                acquisition_obj = hierarchy.update_container_hierarchy(file_store.metadata, acquisition_id, level)
            except APIStorageException as e:
                self.abort(400, e.message)
            # move the files before updating the database
            for name, parsed_file in file_store.files.items():
                fileinfo = parsed_file.info
                target_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
                files.move_file(parsed_file.path, target_path)
            # merge infos from the actual file and from the metadata
            merged_files = hierarchy.merge_fileinfos(file_store.files, file_infos)
            # update the fileinfo in mongo if a file already exists
            for f in acquisition_obj['files']:
                merged_file = merged_files.get(f['name'])
                if merged_file:
                    fileinfo = merged_file.info
                    fileinfo['modified'] = now
                    acquisition_obj = hierarchy.update_fileinfo('acquisitions', acquisition_obj['_id'], fileinfo)
                    fileinfo['existing'] = True
            # create the missing fileinfo in mongo
            for name, merged_file in merged_files.items():
                fileinfo = merged_file.info
                # if the file exists we don't need to create it
                # skip update fileinfo for files that don't have a path
                if not fileinfo.get('existing') and merged_file.path:
                    fileinfo['mimetype'] = fileinfo.get('mimetype') or util.guess_mimetype(name)
                    fileinfo['created'] = now
                    fileinfo['modified'] = now
                    fileinfo['origin'] = self.origin
                    acquisition_obj = hierarchy.add_fileinfo('acquisitions', acquisition_obj['_id'], fileinfo)

            for f in acquisition_obj['files']:
                if f['name'] in file_store.files:
                    file_ = {
                        'name': f['name'],
                        'hash': f['hash'],
                        'type': f.get('type'),
                        'measurements': f.get('measurements', []),
                        'mimetype': f.get('mimetype')
                    }
                    rules.create_jobs(config.db, acquisition_obj, 'acquisition', file_)
            return [{'name': k, 'hash': v.info.get('hash'), 'size': v.info.get('size')} for k, v in merged_files.items()]

    def clean_packfile_tokens(self):
        """
        .. http:post:: /api/clean-packfiles

            Clean up expired upload tokens and invalid token directories.

            :statuscode 402: describe me
        """

        """
        Ref placer.TokenPlacer and FileListHandler.packfile_start for context.
        """

        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')

        # Race condition: we could delete tokens & directories that are currently processing.
        # For this reason, the modified timeout is long.
        result = config.db['tokens'].delete_many({
            'type': 'packfile',
            'modified': {'$lt': datetime.datetime.utcnow() - datetime.timedelta(hours=1)},
        })

        removed = result.deleted_count
        if removed > 0:
            log.info('Removed ' + str(removed) + ' expired packfile tokens')

        # Next, find token directories and remove any that don't map to a token.

        # This logic is used by:
        #   TokenPlacer.check
        #   PackfilePlacer.check
        #   upload.clean_packfile_tokens
        #
        # It must be kept in sync between each instance.
        base = config.get_item('persistent', 'data_path')
        folder = os.path.join(base, 'tokens', 'packfile')

        util.mkdir_p(folder)
        paths = os.listdir(folder)
        cleaned = 0

        for token in paths:
            path = os.path.join(folder, token)

            result = None
            try:
                result = config.db['tokens'].find_one({
                    '_id': token
                })
            except bson.errors.InvalidId:
                # Folders could be an invalid mongo ID, in which case they're definitely expired :)
                pass

            if result is None:
                log.info('Cleaning expired token directory ' + token)
                shutil.rmtree(path)
                cleaned += 1

        return {
            'removed': {
                'tokens': removed,
                'directories': cleaned,
            }
        }
