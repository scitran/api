import bson
import copy
import datetime
import dateutil
import os
import pymongo
import shutil
import zipfile

from backports import tempfile

from . import config
from . import files
from . import util
from . import validators
from .dao import containerutil, hierarchy
from .dao.containerstorage import SessionStorage, AcquisitionStorage
from .jobs import rules
from .jobs.jobs import Job, JobTicket
from .jobs.queue import Queue
from .types import Origin
from .web import encoder
from .web.errors import FileFormException

class Placer(object):
    """
    Interface for a placer, which knows how to process files and place them where they belong - on disk and database.
    """

    def __init__(self, container_type, container, id_, metadata, timestamp, origin, context):
        self.container_type = container_type
        self.container      = container
        self.id_            = id_
        self.metadata       = metadata
        self.timestamp      = timestamp

        # An origin map for the caller
        self.origin         = origin

        # A placer-defined map for breaking the Placer abstraction layer.
        self.context        = context

        # Should the caller expect a normal map return, or a generator that gets mapped to Server-Sent Events?
        self.sse            = False

        # A list of files that have been saved via save_file() usually returned by finalize()
        self.saved          = []


    def check(self):
        """
        Run any pre-processing checks. Expected to throw on error.
        """
        raise NotImplementedError() # pragma: no cover

    def process_file_field(self, field, file_attrs):
        """"
        Process a single file field.
        """
        raise NotImplementedError() # pragma: no cover

    def finalize(self):
        """
        Run any post-processing work. Expected to return output for the callee.
        """
        raise NotImplementedError() # pragma: no cover

    def requireTarget(self):
        """
        Helper function that throws unless a container was provided.
        """
        if self.id_ is None or self.container is None or self.container_type is None:
            raise Exception('Must specify a target')

    def requireMetadata(self):
        """
        Helper function that throws unless metadata was provided.
        """
        if self.metadata == None:
            raise FileFormException('Metadata required')

    def save_file(self, field=None, file_attrs=None):
        """
        Helper function that moves a file saved via a form field into our CAS.
        May trigger jobs, if applicable, so this should only be called once we're ready for that.

        Requires an augmented file field; see process_upload() for details.
        """

        # Save file
        if field is not None:
            files.move_form_file_field_into_cas(field)

        # Update the DB
        if file_attrs is not None:
            container_before, self.container = hierarchy.upsert_fileinfo(self.container_type, self.id_, file_attrs)

            # Queue any jobs as a result of this upload, uploading to a gear will not make jobs though
            if self.container_type != 'gear':
                rules.create_jobs(config.db, container_before, self.container, self.container_type)

    def recalc_session_compliance(self):
        if self.container_type in ['session', 'acquisition'] and self.id_:
            if self.container_type == 'session':
                session_id = self.id_
            else:
                session_id = AcquisitionStorage().get_container(str(self.id_)).get('session')
            SessionStorage().recalc_session_compliance(session_id, hard=True)

class TargetedPlacer(Placer):
    """
    A placer that can accept N files to a specific container (acquisition, etc).

    LIMITATION: To temporarily avoid messing with the JSON schema, this endpoint can only consume one file :(
    An exception is thrown in upload.process_upload() if you try. This could be fixed by making a better schema.
    """

    def check(self):
        self.requireTarget()
        validators.validate_data(self.metadata, 'file.json', 'input', 'POST', optional=True)

    def process_file_field(self, field, file_attrs):
        if self.metadata:
            file_attrs.update(self.metadata)
        self.save_file(field, file_attrs)
        self.saved.append(file_attrs)

    def finalize(self):
        self.recalc_session_compliance()
        return self.saved

class UIDPlacer(Placer):
    """
    A placer that can accept multiple files.
    It uses the method upsert_top_down_hierarchy to create its project/session/acquisition hierarchy
    Sessions and acquisitions are identified by UID.
    """
    metadata_schema = 'uidupload.json'
    create_hierarchy = staticmethod(hierarchy.upsert_top_down_hierarchy)
    match_type = 'uid'

    def __init__(self, container_type, container, id_, metadata, timestamp, origin, context):
        super(UIDPlacer, self).__init__(container_type, container, id_, metadata, timestamp, origin, context)
        self.metadata_for_file = {}
        self.session_id = None
        self.count = 0

    def check(self):
        self.requireMetadata()

        payload_schema_uri = validators.schema_uri('input', self.metadata_schema)
        metadata_validator = validators.from_schema_path(payload_schema_uri)
        metadata_validator(self.metadata, 'POST')



    def process_file_field(self, field, file_attrs):
        # Only create the hierarchy once
        if self.count == 0:
            # If not a superuser request, pass uid of user making the upload request
            targets = self.create_hierarchy(self.metadata, type_=self.match_type, user=self.context.get('uid'))

            self.metadata_for_file = {}

            for target in targets:
                if target[0].level is 'session':
                    self.session_id = target[0].id_
                for name in target[1]:
                    self.metadata_for_file[name] = {
                        'container': target[0],
                        'metadata': target[1][name]
                    }
        self.count += 1

        # For the file, given self.targets, choose a target
        name        = field.filename
        target      = self.metadata_for_file.get(name)

        # if the file was not included in the metadata skip it
        if not target:
            return
        container   = target['container']
        r_metadata  = target['metadata']
        file_attrs.update(r_metadata)

        if container.level != 'subject':
            self.container_type = container.level
            self.id_            = container.id_
            self.container      = container.container
            self.save_file(field, file_attrs)
        else:
            if field is not None:
                files.move_form_file_field_into_cas(field)
            if file_attrs is not None:
                container.upsert_file(file_attrs)

                # # Queue any jobs as a result of this upload
                # rules.create_jobs(config.db, self.container, self.container_type, info)

        self.saved.append(file_attrs)

    def finalize(self):
        # Check that there is at least one file being uploaded
        if self.count < 1:
            raise FileFormException("No files selected for upload")
        if self.session_id:
            self.container_type = 'session'
            self.id_ = self.session_id
            self.recalc_session_compliance()
        return self.saved

class UIDReaperPlacer(UIDPlacer):
    """
    A placer that creates or matches based on UID.

    Ignores project and group information if it finds session with matching UID.
    Allows users to move sessions during scans without causing new data to be
    created in referenced project/group.
    """

    metadata_schema = 'uidupload.json'
    create_hierarchy = staticmethod(hierarchy.upsert_bottom_up_hierarchy)
    match_type = 'uid'

class LabelPlacer(UIDPlacer):
    """
    A placer that create a hierarchy based on labels.

    It uses the method upsert_top_down_hierarchy to create its project/session/acquisition hierarchy
    Sessions and acquisitions are identified by label.
    """

    metadata_schema = 'labelupload.json'
    create_hierarchy = staticmethod(hierarchy.upsert_top_down_hierarchy)
    match_type = 'label'

class UIDMatchPlacer(UIDPlacer):
    """
    A placer that uploads to an existing hierarchy it finds based on uid.
    """

    metadata_schema = 'uidmatchupload.json'
    create_hierarchy = staticmethod(hierarchy.find_existing_hierarchy)
    match_type = 'uid'

class EnginePlacer(Placer):
    """
    A placer that can accept files and/or metadata sent to it from the engine

    It uses update_container_hierarchy to update the container and its parents' fields from the metadata
    """

    def check(self):
        self.requireTarget()

        # Check that required state exists
        if self.context.get('job_id'):
            Job.get(self.context.get('job_id'))
        if self.context.get('job_ticket_id'):
            JobTicket.get(self.context.get('job_ticket_id'))

        if self.metadata is not None:
            validators.validate_data(self.metadata, 'enginemetadata.json', 'input', 'POST', optional=True)

            ###
            # Shuttle `measurements` key into `classification` on files
            ###

            if self.metadata.get(self.container_type, {}): # pragma: no cover

                for f in self.metadata[self.container_type].get('files', []):

                    if 'measurements' in f:
                        m = f.pop('measurements')
                        f['classification'] = {'Custom': m}
            ###

    def process_file_field(self, field, file_attrs):
        if self.metadata is not None:
            file_mds = self.metadata.get(self.container_type, {}).get('files', [])

            for file_md in file_mds:
                if file_md['name'] == file_attrs['name']:
                    file_attrs.update(file_md)
                    break

        if self.context.get('job_ticket_id'):
            job_ticket = JobTicket.get(self.context.get('job_ticket_id'))

            if not job_ticket['success']:
                file_attrs['from_failed_job'] = True

        self.save_file(field, file_attrs)
        self.saved.append(file_attrs)

    def finalize(self):
        job = None
        job_ticket = None
        success = True

        if self.context.get('job_ticket_id'):
            job_ticket = JobTicket.get(self.context.get('job_ticket_id'))
            job = Job.get(job_ticket['job'])
            success = job_ticket['success']

        if self.metadata is not None:
            bid = bson.ObjectId(self.id_)

            file_mds = self.metadata.get(self.container_type, {}).get('files', [])
            saved_file_names = [x.get('name') for x in self.saved]
            for file_md in file_mds:
                if file_md['name'] not in saved_file_names:
                    self.save_file(None, file_md) # save file_attrs update only
                    self.saved.append(file_md)

            # Remove file metadata as it was already updated in process_file_field
            for k in self.metadata.keys():
                self.metadata[k].pop('files', {})

            if success:
                hierarchy.update_container_hierarchy(self.metadata, bid, self.container_type)

        if job_ticket is not None:
            if success:
                Queue.mutate(job, {
                    'state': 'complete',
                    'profile': {
                        'elapsed': job_ticket['elapsed']
                    }
                })
            else:
                Queue.mutate(job, {
                    'state': 'failed',
                    'profile': {
                        'elapsed': job_ticket['elapsed']
                    }
                })

        if self.context.get('job_id'):
            job = Job.get(self.context.get('job_id'))
            job.saved_files = [f['name'] for f in self.saved]
            job.produced_metadata = self.metadata
            job.save()

        self.recalc_session_compliance()
        return self.saved

class TokenPlacer(Placer):
    """
    A placer that can accept N files and save them to a persistent directory across multiple requests.
    Intended for use with a token that tracks where the files will be stored.
    """

    def __init__(self, container_type, container, id_, metadata, timestamp, origin, context):
        super(TokenPlacer, self).__init__(container_type, container, id_, metadata, timestamp, origin, context)

        self.paths  =   []
        self.folder =   None

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
        base_path = config.get_item('persistent', 'data_path')
        self.folder = os.path.join(base_path, 'tokens', 'packfile', token)

        util.mkdir_p(self.folder)

    def process_file_field(self, field, file_attrs):
        self.saved.append(file_attrs)
        self.paths.append(field.path)

    def finalize(self):
        for path in self.paths:
            dest = os.path.join(self.folder, os.path.basename(path))
            shutil.move(path, dest)
        self.recalc_session_compliance()
        return self.saved

class PackfilePlacer(Placer):
    """
    A placer that can accept N files, save them into a zip archive, and place the result on an acquisition.
    """

    def __init__(self, container_type, container, id_, metadata, timestamp, origin, context):
        super(PackfilePlacer, self).__init__(container_type, container, id_, metadata, timestamp, origin, context)

        # This endpoint is an SSE endpoint
        self.sse            = True

        # Populated in check(), used in finalize()
        self.p_id           = None
        self.s_label        = None
        self.s_code         = None
        self.a_label        = None
        self.a_time         = None
        self.g_id           = None

        self.permissions    = {}
        self.folder         = None
        self.dir_           = None
        self.name           = None
        self.path           = None
        self.zip_           = None
        self.ziptime        = None
        self.tempdir        = None


    def check(self):

        token = self.context['token']

        if token is None:
            raise Exception('PackfilePlacer requires a token')

        # This logic is used by:
        #   TokenPlacer.check
        #   PackfilePlacer.check
        #   upload.clean_packfile_tokens
        #
        # It must be kept in sync between each instance.
        base_path = config.get_item('persistent', 'data_path')
        self.folder = os.path.join(base_path, 'tokens', 'packfile', token)

        if not os.path.isdir(self.folder):
            raise Exception('Packfile directory does not exist or has been deleted')

        self.requireMetadata()
        validators.validate_data(self.metadata, 'packfile.json', 'input', 'POST')

        # Save required fields
        self.p_id  = self.metadata['project']['_id']
        self.s_label = self.metadata['session']['label']
        self.a_label = self.metadata['acquisition']['label']

        # Save additional fields if provided
        self.s_code = self.metadata['session'].get('subject', {}).get('code')
        self.a_time = self.metadata['acquisition'].get('timestamp')
        if self.a_time:
            self.a_time = dateutil.parser.parse(self.a_time)

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
        self.dir_ = util.sanitize_string_to_filename(self.a_label)
        self.name = self.dir_ + '.zip'

        # Make a tempdir to store zip until moved
        # OPPORTUNITY: this is also called in files.py. Could be a util func.
        self.tempdir = tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path'))

        # Create a zip in the tempdir that later gets moved into the CAS.
        self.path = os.path.join(self.tempdir.name, 'temp.zip')
        self.zip_  = zipfile.ZipFile(self.path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True)

        # OPPORTUNITY: add zip comment
        # self.zip.comment = json.dumps(metadata, default=metadata_encoder)

        # Bit of a silly hack: write our tempdir directory into the zip (not including its contents).
        # Creates an empty directory entry in the zip which will hold all the files inside.
        # This way, when you expand a zip, you'll get folder/things instead of a thousand dicoms splattered everywhere.
        self.zip_.write(self.tempdir.name, self.dir_)

    def process_file_field(self, field, file_attrs):
        # Should not be called with any files
        raise Exception('Files must already be uploaded')

    def finalize(self):

        paths = os.listdir(self.folder)
        total = len(paths)

        # Write all files to zip
        complete = 0
        for path in paths:
            p = os.path.join(self.folder, path)

            # Set the file's mtime & atime.
            os.utime(p, (self.ziptime, self.ziptime))

            # Place file into the zip folder we created before
            self.zip_.write(p, os.path.join(self.dir_, os.path.basename(path)))

            # Report progress
            complete += 1
            yield encoder.json_sse_pack({
                'event': 'progress',
                'data': { 'done': complete, 'total': total, 'percent': (complete / float(total)) * 100 },
            })

        self.zip_.close()

        # Remove the folder created by TokenPlacer
        shutil.rmtree(self.folder)

        # Lookup uid on token
        token  = self.context['token']
        uid = config.db['tokens'].find_one({ '_id': token }).get('user')
        self.origin = {
            'type': str(Origin.user),
            'id': uid
        }


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

        # Similarly, create the attributes map that is consumed by helper funcs. Clear duplication :(
        # This could be coalesced into a single map thrown on file fields, for example.
        # Used in the API return.
        cgi_attrs = {
            'name':	 cgi_field.filename,
            'modified': cgi_field.modified,
            'size':	 cgi_field.size,
            'hash':	 cgi_field.hash,
            'mimetype': cgi_field.mimetype,

            'type': self.metadata['packfile']['type'],

            # OPPORTUNITY: packfile endpoint could be extended someday to take additional metadata.
            'modality': None,
            'classification': {},
            'tags': [],
            'info': {},

            # Manually add the file orign to the packfile metadata.
            # This is set by upload.process_upload on each file, but we're not storing those.
            'origin': self.origin
        }

        # Get or create a session based on the hierarchy and provided labels.
        query = {
            'project': bson.ObjectId(self.p_id),
            'label': self.s_label,
            'group': self.g_id,
            'deleted': {'$exists': False}
        }

        if self.s_code:
            # If they supplied a subject code, use that in the query as well
            query['subject.code'] = self.s_code

        # Updates if existing
        updates = {}
        updates['permissions'] = self.permissions
        updates['modified']    = self.timestamp
        updates = util.mongo_dict(updates)

        # Extra properties on insert
        insert_map = copy.deepcopy(query)

        # Remove query term that should not become part of the payload
        insert_map.pop('subject.code', None)
        insert_map.pop('deleted')

        insert_map['created'] = self.timestamp
        insert_map.update(self.metadata['session'])
        insert_map['subject'] = containerutil.add_id_to_subject(insert_map.get('subject'), bson.ObjectId(self.p_id))
        if 'timestamp' in insert_map:
            insert_map['timestamp'] = dateutil.parser.parse(insert_map['timestamp'])

        session = config.db.sessions.find_one_and_update(
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
            'deleted': {'$exists': False}
        }

        if self.a_time:
            # If they supplied an acquisition timestamp, use that in the query as well
            query['timestamp'] = self.a_time


        # Updates if existing
        updates = {}
        updates['permissions'] = self.permissions
        updates['modified']    = self.timestamp
        updates = util.mongo_dict(updates)

        # Extra properties on insert
        insert_map = copy.deepcopy(query)

        # Remove query term that should not become part of the payload
        insert_map.pop('deleted')

        insert_map['created'] = self.timestamp
        insert_map.update(self.metadata['acquisition'])
        if 'timestamp' in insert_map:
            insert_map['timestamp'] = dateutil.parser.parse(insert_map['timestamp'])

        acquisition = config.db.acquisitions.find_one_and_update(
            query, {
                '$set': updates,
                '$setOnInsert': insert_map
            },
            upsert=True,
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

        # Set instance target for helper func
        self.container_type = 'acquisition'
        self.id_            = str(acquisition['_id'])
        self.container	    = acquisition

        self.save_file(cgi_field, cgi_attrs)

        # Set target for session recalc
        self.container_type = 'session'
        self.id_            = str(session['_id'])
        self.container      = session

        self.recalc_session_compliance()

        # Delete token
        config.db['tokens'].delete_one({ '_id': token })

        result = {
            'acquisition_id': str(acquisition['_id']),
            'session_id':	 str(session['_id']),
            'info': cgi_attrs
        }

        # Report result
        yield encoder.json_sse_pack({
            'event': 'result',
            'data': result,
        })

class AnalysisPlacer(Placer):

    def check(self):
        self.requireMetadata()
        validators.validate_data(self.metadata, 'analysis.json', 'input', 'POST', optional=True)

    def process_file_field(self, field, file_attrs):
        self.save_file(field)
        self.saved.append(file_attrs)

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
        return self.metadata

class AnalysisJobPlacer(Placer):
    def check(self):
        if self.id_ is None:
            raise Exception('Must specify a target analysis')

        # Check that required state exists
        if self.context.get('job_id'):
            Job.get(self.context.get('job_id'))
        if self.context.get('job_ticket_id'):
            JobTicket.get(self.context.get('job_ticket_id'))

    def process_file_field(self, field, file_attrs):
        if self.metadata is not None:
            file_mds = self.metadata.get('acquisition', {}).get('files', [])

            for file_md in file_mds:
                if file_md['name'] == file_attrs['name']:
                    file_attrs.update(file_md)
                    break

        file_attrs['output'] = True
        file_attrs['created'] = file_attrs['modified']
        self.save_file(field)
        self.saved.append(file_attrs)

    def finalize(self):
        # Search the sessions table for analysis, replace file field
        if self.saved:
            q = {'_id': self.id_}
            u = {'$push': {'files': {'$each': self.saved}}}
            job_id = self.context.get('job_id')
            if job_id:
                # If the original job failed, update the analysis with the job that succeeded
                u['$set'] = {'job': job_id}

                # Update the job with saved files list
                job = Job.get(job_id)
                job.saved_files = [f['name'] for f in self.saved]
                job.save()

            config.db.analyses.update_one(q, u)
            return self.saved

class GearPlacer(Placer):
    def check(self):
        self.requireMetadata()

    def process_file_field(self, field, file_attrs):
        if self.metadata:
            file_attrs.update(self.metadata)
            proper_hash = file_attrs.get('hash')[3:].replace('-', ':')
            self.metadata.update({'exchange': {'rootfs-hash': proper_hash,
                                               'git-commit': 'local',
                                               'rootfs-url': 'INVALID'}})
        # self.metadata['hash'] = file_attrs.get('hash')
        self.save_file(field)
        self.saved.append(file_attrs)
        self.saved.append(self.metadata)

    def finalize(self):
        return self.saved
