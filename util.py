# @author:  Gunnar Schaefer

import logging
log = logging.getLogger('scitran.api')

import os
import bson
import copy
import json
import pytz
import uuid
import shutil
import difflib
import hashlib
import tarfile
import datetime
import mimetypes
import dateutil.parser
import tempdir as tempfile

import scitran.data
import scitran.data.medimg.montage

mimetypes.types_map.update({'.bvec': 'text/plain'})
mimetypes.types_map.update({'.bval': 'text/plain'})

get_info = scitran.data.medimg.montage.get_info
get_tile = scitran.data.medimg.montage.get_tile

valid_timezones = pytz.all_timezones

PROJECTION_FIELDS = ['group', 'timestamp', 'permissions', 'public']


def parse_file(filepath, digest):
    filename = os.path.basename(filepath)
    try:
        log.info('Parsing     %s' % filename)
        dataset = scitran.data.parse(filepath)
    except scitran.data.DataError:
        log.info('Unparsable  %s' % filename)
        return None
    filename = dataset.nims_file_name + dataset.nims_file_ext
    fileinfo = {
            'mimetype': guess_mimetype(filename),
            'filename': filename,
            'filesize': os.path.getsize(filepath),
            'filetype': dataset.nims_file_type,
            'filehash': digest,
            'datahash': None, #dataset.nims_hash, TODO: datasets should be able to hash themselves (but not here)
            'modality': dataset.nims_file_domain,
            'datatypes': dataset.nims_file_kinds,
            'flavor': 'data',
            }
    datainfo = {
            'acquisition_id': dataset.nims_acquisition_id,
            'session_id': dataset.nims_session_id,
            'group_id': dataset.nims_group_id,
            'project_name': dataset.nims_project,
            'session_properties': _entity_metadata(dataset, dataset.session_properties),
            'acquisition_properties': _entity_metadata(dataset, dataset.acquisition_properties),
            'timestamp': dataset.nims_timestamp,
            'timezone': dataset.nims_timezone,
            }
    datainfo['fileinfo'] = fileinfo
    # HACK!!!
    datainfo['acquisition_properties'].pop('filetype', None)
    if fileinfo['filetype'] == 'dicom' and fileinfo['datatypes'][0] != 'screenshot':
        datainfo['acquisition_properties']['modality'] = fileinfo['modality']
        datainfo['acquisition_properties']['datatype'] = fileinfo['datatypes'][0]
    return datainfo


def quarantine_file(filepath, quarantine_path):
    q_path = tempfile.mkdtemp(prefix=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_'), dir=quarantine_path)
    shutil.move(filepath, q_path)


def commit_file(dbc, _id, datainfo, filepath, data_path):
    """Insert a file as an attachment or as a file."""
    filename = os.path.basename(filepath)
    fileinfo = datainfo['fileinfo']
    log.info('Sorting     %s' % filename)
    if _id is None:
        _id = _update_db(dbc.database, datainfo)
    #create_job(dbc, dataset) # FIXME we should only mark files as new and let engine take it from there
    container_path = os.path.join(data_path, str(_id)[-3:] + '/' + str(_id))
    if not os.path.exists(container_path):
        os.makedirs(container_path)
    r = dbc.update_one({'_id':_id, 'files.filename': fileinfo['filename']}, {'$set': {'files.$': fileinfo}})
    #TODO figure out if file was actually updated and return that fact
    if r.matched_count != 1:
        dbc.update({'_id': _id}, {'$push': {'files': fileinfo}})
    shutil.move(filepath, container_path + '/' + fileinfo['filename'])
    log.debug('Done        %s' % filename)


def _update_db(db, datainfo):
    #TODO: possibly try to keep a list of session IDs on the project, instead of having the session point to the project
    #      same for the session and acquisition
    #      queries might be more efficient that way
    session_spec = {'uid': datainfo['session_id']}
    session = db.sessions.find_one(session_spec, ['project'])
    if session: # skip project creation, if session exists
        project = db.projects.find_one({'_id': session['project']}, projection=PROJECTION_FIELDS + ['name'])
    else:
        existing_group_ids = [g['_id'] for g in db.groups.find(None, ['_id'])]
        group_id_matches = difflib.get_close_matches(datainfo['group_id'], existing_group_ids, cutoff=0.8)
        if len(group_id_matches) == 1:
            group_id = group_id_matches[0]
            project_name = datainfo['project_name'] or 'untitled'
        else:
            group_id = 'unknown'
            project_name = datainfo['group_id'] + ('/' + datainfo['project_name'] if datainfo['project_name'] else '')
        group = db.groups.find_one({'_id': group_id})
        project_spec = {'group': group['_id'], 'name': project_name}
        project = db.projects.find_and_modify(
                project_spec,
                {'$setOnInsert': {'permissions': group['roles'], 'public': False, 'files': []}},
                upsert=True,
                new=True,
                projection=PROJECTION_FIELDS,
                )
    session = db.sessions.find_and_modify(
            session_spec,
            {
                '$setOnInsert': dict(group=project['group'], project=project['_id'], permissions=project['permissions'], public=project['public'], files=[]),
                '$set': datainfo['session_properties'] or session_spec, # session_spec ensures non-empty $set
                #'$addToSet': {'modalities': datainfo['fileinfo']['modality']}, # FIXME
                },
            upsert=True,
            new=True,
            projection=PROJECTION_FIELDS,
            )
    acquisition_spec = {'uid': datainfo['acquisition_id']}
    acquisition = db.acquisitions.find_and_modify(
            acquisition_spec,
            {
                '$setOnInsert': dict(session=session['_id'], permissions=session['permissions'], public=session['public'], files=[]),
                '$set': datainfo['acquisition_properties'] or acquisition_spec, # acquisition_spec ensures non-empty $set
                #'$addToSet': {'types': {'$each': [{'domain': dataset.nims_file_domain, 'kind': kind} for kind in dataset.nims_file_kinds]}},
                },
            upsert=True,
            new=True,
            projection=[],
            )
    if datainfo['timestamp']:
        db.projects.update({'_id': project['_id']}, {'$max': dict(timestamp=datainfo['timestamp']), '$set': dict(timezone=datainfo['timezone'])})
        db.sessions.update({'_id': session['_id']}, {'$min': dict(timestamp=datainfo['timestamp']), '$set': dict(timezone=datainfo['timezone'])})
    return acquisition['_id']


def _entity_metadata(dataset, properties, metadata={}, parent_key=''):
    metadata = copy.deepcopy(metadata)
    if dataset.nims_metadata_status is not None:
        parent_key = parent_key and parent_key + '.'
        for key, attributes in properties.iteritems():
            if attributes['type'] == 'object':
                metadata.update(_entity_metadata(dataset, attributes['properties'], parent_key=key))
            else:
                value = getattr(dataset, attributes['field']) if 'field' in attributes else None
                if value or value == 0: # drop Nones and empty iterables
                    metadata[parent_key + key] = value
    return metadata


# TODO: create job should be use-able from bootstrap.py with only database information
def create_job(dbc, dataset):
    db = dbc.database
    type_ = dataset.nims_file_type
    kinds_ = dataset.nims_file_kinds
    state_ = dataset.nims_file_state
    app = None
    # TODO: check if there are 'default apps' set for this project/session/acquisition
    acquisition = db.acquisitions.find_one({'uid': dataset.nims_acquisition_id})
    session = db.sessions.find_one({'_id': bson.ObjectId(acquisition.get('session'))})
    project = db.projects.find_one({'_id': bson.ObjectId(session.get('project'))})
    aid = acquisition.get('_id')

    # XXX: if an input kinds = None, then that job is meant to work on any file kinds
    app = db.apps.find_one({
        '$or': [
            {'inputs': {'$elemMatch': {'type': type_, 'state': state_, 'kinds': kinds_}}, 'default': True},
            {'inputs': {'$elemMatch': {'type': type_, 'state': state_, 'kinds': None}}, 'default': True},
        ],
    })
    # TODO: this has to move...
    # force acquisition dicom file to be marked as 'optional = True'
    db.acquisitions.find_and_modify(
        {'uid': dataset.nims_acquisition_id, 'files.type': 'dicom'},
        {'$set': {'files.$.optional': True}},
        )

    if not app:
        log.info('no app for type=%s, state=%s, kinds=%s, default=True. no job created.' % (type_, state_, kinds_))
    else:
        # XXX: outputs can specify to __INHERIT__ a value from the parent input file, for ex: kinds
        for output in app['outputs']:
            if output['kinds'] == '__INHERIT__':
                output['kinds'] = kinds_

        # TODO: job description needs more metadata to be searchable in a useful way
        output_url = '%s/%s/%s' % ('acquisitions', aid, 'file')
        job = db.jobs.find_and_modify(
            {
                '_id': db.jobs.count() + 1,
            },
            {
                '_id': db.jobs.count() + 1,
                'group': project.get('group'),
                'project': {
                    '_id': project.get('_id'),
                    'name': project.get('name'),
                },
                'exam': session.get('exam'),
                'app': {
                    '_id': app['_id'],
                    'type': 'docker',
                },
                'inputs': [
                    {
                        'filename': dataset.nims_file_name + dataset.nims_file_ext,
                        'url': '%s/%s/%s' % ('acquisitions', aid, 'file'),
                        'payload': {
                            'type': dataset.nims_file_type,
                            'state': dataset.nims_file_state,
                            'kinds': dataset.nims_file_kinds,
                        },
                    }
                ],
                'outputs': [{'url': output_url, 'payload': i} for i in app['outputs']],
                'status': 'pending',
                'activity': None,
                'added': datetime.datetime.now(),
                'timestamp': datetime.datetime.now(),
            },
            upsert=True,
            new=True,
        )
        log.info('created job %d, group: %s, project %s' % (job['_id'], job['group'], job['project']))


def insert_app(db, fp, apps_path, app_meta=None):
    """Validate and insert an application tar into the filesystem and database."""
    # download, md-5 check, and json validation are handled elsewhere
    if not app_meta:
        with tarfile.open(fp) as tf:
            for ti in tf:
                if ti.name.endswith('description.json'):
                    app_meta = json.load(tf.extractfile(ti))
                    break

    name, version = app_meta.get('_id').split(':')
    app_dir = os.path.join(apps_path, name)
    if not os.path.exists(app_dir):
        os.makedirs(app_dir)
    app_tar = os.path.join(app_dir, '%s-%s.tar' % (name, version))

    app_meta.update({'asset_url': 'apps/%s' % app_meta.get('_id')})
    db.apps.update({'_id': app_meta.get('_id')}, app_meta, upsert=True)
    shutil.move(fp, app_tar)


def hrsize(size):
    if size < 1000:
        return '%d%s' % (size, 'B')
    for suffix in 'KMGTPEZY':
        size /= 1024.
        if size < 10.:
            return '%.1f%s' % (size, suffix)
        if size < 1000.:
            return '%.0f%s' % (size, suffix)
    return '%.0f%s' % (size, 'Y')


def mongo_dict(d):
    def _mongo_list(d, pk=''):
        pk = pk and pk + '.'
        return sum([_mongo_list(v, pk+k) if isinstance(v, dict) else [(pk+k, v)] for k, v in d.iteritems()], [])
    return dict(_mongo_list(d))


def user_perm(permissions, _id, site=None):
    for perm in permissions:
        if perm['_id'] == _id and perm.get('site') == site:
            return perm
    else:
        return {}


def upload_ticket(**kwargs):
    ticket = {
        '_id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.utcnow(),
    }
    ticket.update(kwargs)
    return ticket


def download_ticket(type_, target, filename, size):
    return {
            '_id': str(uuid.uuid4()),
            'timestamp': datetime.datetime.utcnow(),
            'type': type_,
            'target': target,
            'filename': filename,
            'size': size,
            }


def receive_stream_and_validate(stream, filepath, valid_md5):
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    with open(filepath, 'wb') as fd:
        for chunk in iter(lambda: stream.read(2**20), ''):
            md5.update(chunk)
            sha1.update(chunk)
            fd.write(chunk)
    return (md5.hexdigest() == valid_md5), sha1.hexdigest()


def guess_mimetype(filepath):
    """Guess MIME type based on filename."""
    mime, _ = mimetypes.guess_type(filepath)
    return mime or 'application/octet-stream'


def guess_filetype(filepath, mimetype):
    """Guess MIME type based on filename."""
    type_, subtype = mimetype.split('/')
    if filepath.endswith('.nii') or filepath.endswith('.nii.gz'):
        return 'nifti'
    elif type_ == 'text' and subtype == 'plain':
        return 'text'
    else:
        return subtype


def format_timestamp(timestamp, tzname=None):
    timezone = pytz.timezone(tzname or 'UTC')
    return timezone.localize(timestamp).isoformat(), timezone.zone


def parse_timestamp(iso_timestamp):
    return dateutil.parser.parse(iso_timestamp)

def format_timestamp(timestamp=None, tzname=None):
    timestamp = timestamp or datetime.datetime.utcnow()
    timezone = pytz.timezone(tzname or 'UTC')
    return timezone.localize(timestamp).isoformat(), timezone.zone
