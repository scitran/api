import bson
import copy
import datetime
import dateutil
import os
import pymongo
import shutil
import zipfile

from . import base
from . import config
from . import encoder
from . import files
from .jobs import rules
from . import tempdir as tempfile
from . import util
from . import validators
from .dao import hierarchy, APIStorageException, containerutil

log = config.log

class Placer(object):
    """
    Interface for a placer, which knows how to process files and place them where they belong - on disk and database.
    """

    def __init__(self, container_type, container, id, metadata, timestamp, origin, context):
        self.container_type = container_type
        self.container      = container
        self.id             = id
        self.metadata       = metadata
        self.timestamp      = timestamp

        # An origin map for the caller
        self.origin         = origin

        # A placer-defined map for breaking the Placer abstraction layer.
        self.context        = context

        # Should the caller expect a normal map return, or a generator that gets mapped to Server-Sent Events?
        self.sse            = False


    def check(self):
        """
        Run any pre-processing checks. Expected to throw on error.
        """
        raise NotImplementedError()

    def process_file_field(self, field, info):
        """"
        Process a single file field.
        """
        raise NotImplementedError()

    def finalize(self):
        """
        Run any post-processing work. Expected to return output for the callee.
        """
        raise NotImplementedError()

    def requireTarget(self):
        """
        Helper function that throws unless a container was provided.
        """
        if self.id is None or self.container is None or self.container_type is None:
            raise Exception('Must specify a target')

    def requireMetadata(self):
        """
        Helper function that throws unless metadata was provided.
        """
        if self.metadata == None:
            raise Exception('Metadata required')

    def save_file(self, field=None, info=None):
        """
        Helper function that moves a file saved via a form field into our CAS.
        May trigger jobs, if applicable, so this should only be called once we're ready for that.

        Requires an augmented file field; see process_upload() for details.
        """

        # Save file
        if field is not None:
            files.move_form_file_field_into_cas(field)

        # Update the DB
        if info is not None:
            hierarchy.upsert_fileinfo(self.container_type, self.id, info)

            # Queue any jobs as a result of this upload
            rules.create_jobs(config.db, self.container, self.container_type, info)


class TargetedPlacer(Placer):
    """
    A placer that can accept N files to a specific container (acquisition, etc).

    LIMITATION: To temporarily avoid messing with the JSON schema, this endpoint can only consume one file :(
    An exception is thrown in upload.process_upload() if you try. This could be fixed by making a better schema.
    """

    def check(self):
        self.requireTarget()
        validators.validate_data(self.metadata, 'file.json', 'input', 'POST', optional=True)
        self.saved = []

    def process_file_field(self, field, info):
        self.save_file(field, info)
        self.saved.append(info)

    def finalize(self):
        return self.saved


class UIDPlacer(Placer):
    """
    A placer that can accept multiple files.
    It uses the method upsert_bottom_up_hierarchy to create its project/session/acquisition hierarchy
    Sessions and acquisitions are identified by UID.
    """
    metadata_schema = 'uidupload.json'
    create_hierarchy = staticmethod(hierarchy.upsert_bottom_up_hierarchy)

    def check(self):
        self.requireMetadata()

        payload_schema_uri = util.schema_uri('input', self.metadata_schema)
        metadata_validator = validators.from_schema_path(payload_schema_uri)
        metadata_validator(self.metadata, 'POST')

        targets = self.create_hierarchy(self.metadata)

        self.metadata_for_file = { }

        for target in targets:
            for name in target[1]:
                self.metadata_for_file[name] = {
                    'container': target[0],
                    'metadata': target[1][name]
                }

        self.saved = []

    def process_file_field(self, field, info):

        # For the file, given self.targets, choose a target

        name        = field.filename
        target      = self.metadata_for_file.get(name)
        # if the file was not included in the metadata skip it
        if not target:
            return
        container   = target['container']
        r_metadata  = target['metadata']

        self.container_type = container.level
        self.id             = container._id
        self.container      = container.container

        info.update(r_metadata)

        self.save_file(field, info)
        self.saved.append(info)

    def finalize(self):
        return self.saved


class LabelPlacer(UIDPlacer):
    """
    A placer that create a hierarchy based on labels.

    It uses the method upsert_top_down_hierarchy to create its project/session/acquisition hierarchy
    Sessions and acquisitions are identified by label.
    """

    metadata_schema = 'labelupload.json'
    create_hierarchy = staticmethod(hierarchy.upsert_top_down_hierarchy)


class EnginePlacer(Placer):
    """
    A placer that can accept files sent to it from an engine.
    Currently a stub.
    """

    def check(self):
        self.requireTarget()
        validators.validate_data(self.metadata, 'enginemetadata.json', 'input', 'POST', optional=True)
        self.saved = []

        # Could avoid loops in process_file_field by setting up the

    def process_file_field(self, field, info):
        if self.metadata is not None:
            # OPPORTUNITY: hard-coded container levels will need to go away soon
            # Engine shouldn't know about container names; maybe parent contexts?
            # How will this play with upload unification? Unify schemas as well?
            file_mds = self.metadata.get('acquisition', {}).get('files', [])

            for file_md in file_mds:
                if file_md['name'] == info['name']:
                    break
            else:
                file_md = {}

            for x in ('type', 'instrument', 'measurements', 'tags', 'metadata'):
                info[x] = file_md.get(x) or info[x]

        self.save_file(field, info)
        self.saved.append(info)

    def finalize(self):
        # Updating various properties of the hierarchy; currently assumes acquisitions; might need fixing for other levels.
        # NOTE: only called in EnginePlacer
        bid = bson.ObjectId(self.id)
        self.obj = hierarchy.update_container_hierarchy(self.metadata, bid, '')

        return self.saved


class TokenPlacer(Placer):
    """
    A placer that can accept N files and save them to a persistent directory across multiple requests.
    Intended for use with a token that tracks where the files will be stored.
    """

    def check(self):
        token = self.context['token']

        if token is None:
            raise Exception('TokenPlacer requires a token')

        # This logic is used by:
        #   TokenPlacer.check
        #   PackfilePlacer.check
        #   upload.clean_packfile_tokens
        #
        # It must be kept in sync between each instance.
        base = config.get_item('persistent', 'data_path')
        self.folder = os.path.join(base, 'tokens', 'packfile', token)

        util.mkdir_p(self.folder)

        self.saved = []
        self.paths = []

    def process_file_field(self, field, info):
        self.saved.append(info)
        self.paths.append(field.path)

    def finalize(self):
        for path in self.paths:
            dest = os.path.join(self.folder, os.path.basename(path))
            shutil.move(path, dest)

        return self.saved


class PackfilePlacer(Placer):
    """
    A placer that can accept N files, save them into a zip archive, and place the result on an acquisition.
    """

    def check(self):
        # This endpoint is an SSE endpoint
        self.sse            = True

        token = self.context['token']

        if token is None:
            raise Exception('PackfilePlacer requires a token')

        # This logic is used by:
        #   TokenPlacer.check
        #   PackfilePlacer.check
        #   upload.clean_packfile_tokens
        #
        # It must be kept in sync between each instance.
        base = config.get_item('persistent', 'data_path')
        self.folder = os.path.join(base, 'tokens', 'packfile', token)

        if not os.path.isdir(self.folder):
            raise Exception('Packfile directory does not exist or has been deleted')

        self.requireMetadata()
        validators.validate_data(self.metadata, 'packfile.json', 'input', 'POST')

        # Save required fields
        self.p_id  = self.metadata['project']['_id']
        self.s_label = self.metadata['session']['label']
        self.a_label = self.metadata['acquisition']['label']

        # Get project info that we need later
        project = config.db['projects'].find_one({ '_id': bson.ObjectId(self.p_id)})
        self.permissions = project.get('permissions', {})
        self.g_id = project['group']

        # If a timestamp was provided, use that for zip files. Otherwise use a set date.
        # Normally we'd use epoch, but zips cannot support years older than 1980, so let's use that instead.
        # Then, given the ISO string, convert it to an epoch integer.
        minimum = datetime.datetime(1980, 1, 1).isoformat()
        stamp   = self.metadata['acquisition'].get('timestamp', minimum)

        # If there was metadata sent back that predates the zip minimum, don't use it.
        #
        # Dateutil has overloaded the comparison operators, except it's totally useless:
        # > TypeError: can't compare offset-naive and offset-aware datetimes
        #
        # So instead, epoch-integer both and compare that way.
        if int(dateutil.parser.parse(stamp).strftime('%s')) < int(dateutil.parser.parse(minimum).strftime('%s')):
            stamp = minimum

        # Remember the timestamp integer for later use with os.utime.
        self.ziptime = int(dateutil.parser.parse(stamp).strftime('%s'))

        # The zipfile is a santizied acquisition label
        self.dir = util.sanitize_string_to_filename(self.a_label)
        self.name = self.dir + '.zip'

        # Make a tempdir to store zip until moved
        # OPPORTUNITY: this is also called in files.py. Could be a util func.
        self.tempdir = tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path'))

        # Create a zip in the tempdir that later gets moved into the CAS.
        self.path = os.path.join(self.tempdir.name, 'temp.zip')
        self.zip  = zipfile.ZipFile(self.path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)

        # OPPORTUNITY: add zip comment
        # self.zip.comment = json.dumps(metadata, default=metadata_encoder)

        # Bit of a silly hack: write our tempdir directory into the zip (not including its contents).
        # Creates an empty directory entry in the zip which will hold all the files inside.
        # This way, when you expand a zip, you'll get folder/things instead of a thousand dicoms splattered everywhere.
        self.zip.write(self.tempdir.name, self.dir)

    def process_file_field(self, field, info):
        # Should not be called with any files
        raise Exception('Files must already be uploaded')

    def finalize(self):

        paths = os.listdir(self.folder)
        max = len(paths)

        # Write all files to zip
        complete = 0
        for path in paths:
            p = os.path.join(self.folder, path)

            # Set the file's mtime & atime.
            os.utime(p, (self.ziptime, self.ziptime))

            # Place file into the zip folder we created before
            self.zip.write(p, os.path.join(self.dir, os.path.basename(path)))

            # Report progress
            complete += 1
            yield encoder.json_sse_pack({
                'event': 'progress',
                'data': { 'done': complete, 'total': max, 'percent': (complete / float(max)) * 100 },
            })

        self.zip.close()

        # Remove the folder created by TokenPlacer
        shutil.rmtree(self.folder)

        # Create an anyonmous object in the style of our augmented file fields.
        # Not a great practice. See process_upload() for details.
        cgi_field = util.obj_from_map({
            'filename': self.name,
            'path':	 self.path,
            'size':	 os.path.getsize(self.path),
            'hash':	 files.hash_file_formatted(self.path),
            'mimetype': util.guess_mimetype('lol.zip'),
            'modified': self.timestamp
        })

        # Similarly, create the info map that is consumed by helper funcs. Clear duplication :(
        # This could be coalesced into a single map thrown on file fields, for example.
        # Used in the API return.
        cgi_info = {
            'name':	 cgi_field.filename,
            'modified': cgi_field.modified,
            'size':	 cgi_field.size,
            'hash':	 cgi_field.hash,

            'type': self.metadata['packfile']['type'],

            # OPPORTUNITY: packfile endpoint could be extended someday to take additional metadata.
            'instrument': None,
            'measurements': [],
            'tags': [],
            'metadata': {},

            # Manually add the file orign to the packfile metadata.
            # This is set by upload.process_upload on each file, but we're not storing those.
            'origin': self.origin
        }

        # Get or create a session based on the hierarchy and provided labels.
        query = {
            'project': bson.ObjectId(self.p_id),
            'label': self.s_label,
            'group': self.g_id
        }

        # Updates if existing
        updates = {}
        updates['permissions'] = self.permissions
        updates['modified']    = self.timestamp
        updates = util.mongo_dict(updates)

        # Extra properties on insert
        insert_map = copy.deepcopy(query)
        insert_map['created'] = self.timestamp
        insert_map.update(self.metadata['session'])
        insert_map['subject'] = containerutil.add_id_to_subject(insert_map.get('subject'), self.p_id)

        session = config.db['session' + 's'].find_one_and_update(
            query, {
                '$set': updates,
                '$setOnInsert': insert_map
            },
            upsert=True,
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

        # Get or create an acquisition based on the hierarchy and provided labels.
        query = {
            'session': session['_id'],
            'label': self.a_label,
        }

        # Updates if existing
        updates = {}
        updates['permissions'] = self.permissions
        updates['modified']    = self.timestamp
        updates = util.mongo_dict(updates)

        # Extra properties on insert
        insert_map = copy.deepcopy(query)
        insert_map['created'] = self.timestamp
        insert_map.update(self.metadata['acquisition'])

        acquisition = config.db['acquisition' + 's'].find_one_and_update(
            query, {
                '$set': updates,
                '$setOnInsert': insert_map
            },
            upsert=True,
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

        # Set instance target for helper func
        self.container_type = 'acquisition'
        self.id			 = str(acquisition['_id'])
        self.container	  = acquisition

        self.save_file(cgi_field, cgi_info)

        # Delete token
        token  = self.context['token']
        config.db['tokens'].delete_one({ '_id': token })

        result = {
            'acquisition_id': str(acquisition['_id']),
            'session_id':	 str(session['_id']),
            'info': cgi_info,
        }

        # Report result
        yield encoder.json_sse_pack({
            'event': 'result',
            'data': result,
        })

class AnalysisPlacer(Placer):

    def check(self):
        self.requireMetadata()
        #validators.validate_data(self.metadata, 'analysys.json', 'input', 'POST', optional=True)
        self.saved = []

    def process_file_field(self, field, info):
        self.save_file(field)
        self.saved.append(info)

    def finalize(self):
        # we are going to merge the "hard" infos from the processed upload
        # with the infos from the payload
        metadata_infos = {}
        for info in self.metadata.pop('inputs', []):
            info['input'] = True
            metadata_infos[info['name']] = info
        for info in self.metadata.pop('outputs', []):
            info['output'] = True
            metadata_infos[info['name']] = info
        self.metadata['files'] = []
        for info in self.saved:
            metadata_info = metadata_infos.get(info['name'], {})
            metadata_info.update(info)
            self.metadata['files'].append(metadata_info)
        self.metadata['_id'] = str(bson.objectid.ObjectId())
        return self.metadata
