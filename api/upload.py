import bson
import os.path
import datetime

from . import base
from . import util
from . import files
from . import rules
from . import config
from .dao import reaperutil, APIStorageException
from . import validators
from . import tempdir as tempfile

log = config.log

class Upload(base.RequestHandler):

    def reaper(self):
        """Receive a sortable reaper upload."""
        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            try:
                file_store = files.FileStore(self.request, tempdir_path)
            except FileStoreException as e:
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
                metadata=file_store.metadata
            )

            target, file_metadata = reaperutil.create_container_hierarchy(file_store.metadata)
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

    def uploader(self):
        """Receive a sortable reaper upload."""
        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            try:
                file_store = files.MultiFileStore(self.request, tempdir_path)
            except FileStoreException as e:
                self.abort(400, str(e))
            if not file_store.metadata:
                self.abort(400, 'metadata is missing')
            metadata_validator = validators.payload_from_schema_file(self, 'uploader.json')
            metadata_validator(file_store.metadata, 'POST')
            try:
                target_containers = reaperutil.create_root_to_leaf_hierarchy(file_store.metadata, file_store.files)
            except APIStorageException as e:
                self.abort(400, str(e))
            for target, file_dict in target_containers:
                for filename, parsed_file in file_dict.items():
                    fileinfo = parsed_file.info
                    f = target.find(filename)
                    target_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
                    if not f:
                        files.move_file(parsed_file.path, target_path)
                        target.add_file(fileinfo)
                        rules.create_jobs(config.db, target.container, target.level[:-1], fileinfo)
                    elif not files.identical(fileinfo['hash'], parsed_file.path, f['hash'], util.path_from_hash(f['hash'])):
                        files.move_file(parsed_file.path, target_path)
                        target.update_file(fileinfo)
                        rules.create_jobs(config.db, target.container, target.level[:-1], fileinfo)

    def engine(self):
        """
        URL format: api/engine?level=<container_type>&id=<container_id>

        It expects a multipart/form-data request with a "metadata" field (json valid against api/schemas/input/enginemetadata)
        and 0 or more file fields with a non null filename property (filename is null for the "metadata").
        """
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
            except FileStoreException as e:
                self.abort(400, str(e))
            if not file_store.metadata:
                self.abort(400, 'metadata is missing')
            metadata_validator = validators.payload_from_schema_file(self, 'enginemetadata.json')
            metadata_validator(file_store.metadata, 'POST')
            file_infos = file_store.metadata['acquisition'].pop('files', [])
            now = datetime.datetime.utcnow()
            try:
                acquisition_obj = reaperutil.update_container_hierarchy(file_store.metadata, acquisition_id, level)
            except APIStorageException as e:
                self.abort(400, e.message)
            # move the files before updating the database
            for name, parsed_file in file_store.files.items():
                fileinfo = parsed_file.info
                target_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
                files.move_file(parsed_file.path, target_path)
            # merge infos from the actual file and from the metadata
            merged_files = reaperutil.merge_fileinfos(file_store.files, file_infos)
            # update the fileinfo in mongo if a file already exists
            for f in acquisition_obj['files']:
                merged_file = merged_files.get(f['name'])
                if merged_file:
                    fileinfo = merged_file.info
                    fileinfo['modified'] = now
                    acquisition_obj = reaperutil.update_fileinfo('acquisitions', acquisition_obj['_id'], fileinfo)
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
                    acquisition_obj = reaperutil.add_fileinfo('acquisitions', acquisition_obj['_id'], fileinfo)

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
