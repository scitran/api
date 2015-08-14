# @author:  Gunnar Schaefer

import logging
log = logging.getLogger('scitran.api')

import os
import copy
import pytz
import uuid
import shutil
import difflib
import hashlib
import zipfile
import datetime
import mimetypes
import dateutil.parser
import tempdir as tempfile

import scitran.data

MIMETYPES = [
    ('.bvec', 'text', 'bvec'),
    ('.bval', 'text', 'bval'),
    ('.m', 'text', 'matlab'),
    ('.sh', 'text', 'shell'),
    ('.r', 'text', 'r'),
]
for mt in MIMETYPES:
    mimetypes.types_map.update({mt[0]: mt[1] + '/' + mt[2]})

valid_timezones = pytz.all_timezones

PROJECTION_FIELDS = ['group', 'timestamp', 'permissions', 'public']


def parse_file(filepath, digest):
    filename = os.path.basename(filepath)
    try:
        log.info('Parsing     %s' % filename)
        dataset = scitran.data.parse(filepath)
    except scitran.data.DataError as exp:
        log.info('Unparsable  %s (%s)' % (filename, exp))
        return None
    filename = dataset.nims_file_name + dataset.nims_file_ext
    fileinfo = {
            'mimetype': guess_mimetype(filename),
            'filename': filename,
            'filesize': os.path.getsize(filepath),
            'filetype': dataset.nims_file_type,
            'filehash': digest,
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


def commit_file(dbc, _id, datainfo, filepath, data_path, force=False):
    """Insert a file as an attachment or as a file."""
    filename = os.path.basename(filepath)
    fileinfo = datainfo['fileinfo']
    log.info('Sorting     %s' % filename)
    if _id is None:
        _id = _update_db(dbc.database, datainfo)
    container_path = os.path.join(data_path, str(_id)[-3:] + '/' + str(_id))
    target_filepath = container_path + '/' + fileinfo['filename']
    if not os.path.exists(container_path):
        os.makedirs(container_path)
    container = dbc.find_one_and_update({'_id':_id, 'files.filename': fileinfo['filename']}, {'$set': {'files.$': fileinfo}})
    if container: # file already exists
        for f in container['files']:
            if f['filename'] == fileinfo['filename']:
                if not force:
                    updated = False
                elif identical_content(target_filepath, f['filehash'], filepath, fileinfo['filehash']): # existing file has identical content
                    log.debug('Dropping    %s (identical)' % filename)
                    os.remove(filepath)
                    updated = None
                else: # existing file has different content
                    log.debug('Replacing   %s' % filename)
                    shutil.move(filepath, target_filepath)
                    dbc.update_one({'_id':_id, 'files.filename': fileinfo['filename']}, {'$set': {'files.$.dirty': True}})
                    updated = True
                break
    else:         # file does not exist
        log.debug('Adding      %s' % filename)
        fileinfo['dirty'] = True
        shutil.move(filepath, target_filepath)
        dbc.update_one({'_id': _id}, {'$push': {'files': fileinfo}})
        updated = True
    log.debug('Done        %s' % filename)
    return updated


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


def identical_content(filepath1, digest1, filepath2, digest2):
    if zipfile.is_zipfile(filepath1) and zipfile.is_zipfile(filepath2):
        with zipfile.ZipFile(filepath1) as zf1, zipfile.ZipFile(filepath2) as zf2:
            zf1_infolist = sorted(zf1.infolist(), key=lambda zi: zi.filename)
            zf2_infolist = sorted(zf2.infolist(), key=lambda zi: zi.filename)
            if zf1.comment != zf2.comment:
                return False
            if len(zf1_infolist) != len(zf2_infolist):
                return False
            for zii, zij in zip(zf1_infolist, zf2_infolist):
                if zii.CRC != zij.CRC:
                    return False
            else:
                return True
    else:
        return digest1 == digest2


def hrsize(size):
    if size < 1000:
        return '%d%s' % (size, 'B')
    for suffix in 'KMGTPEZY':
        size /= 1024.
        if size < 10.:
            return '%.1f%sB' % (size, suffix)
        if size < 1000.:
            return '%.0f%sB' % (size, suffix)
    return '%.0f%sB' % (size, 'Y')


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


def container_fileinfo(container, filename):
    for fileinfo in container.get('files', []):
        if fileinfo['filename'] == filename:
            return fileinfo
    else:
        return None


def upload_ticket(ip, **kwargs):
    ticket = {
        '_id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.utcnow(),
        'ip': ip,
    }
    ticket.update(kwargs)
    return ticket


def download_ticket(ip, type_, target, filename, size):
    return {
        '_id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.utcnow(),
        'ip': ip,
        'type': type_,
        'target': target,
        'filename': filename,
        'size': size,
    }


def receive_stream_and_validate(stream, filepath, received_md5):
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    filesize = 0
    start_time = datetime.datetime.utcnow()
    with open(filepath, 'wb') as fd:
        for chunk in iter(lambda: stream.read(2**20), ''):
            md5.update(chunk)
            sha1.update(chunk)
            filesize += len(chunk)
            fd.write(chunk)
    duration = datetime.datetime.utcnow() - start_time
    return (md5.hexdigest() == received_md5) if received_md5 is not None else True, sha1.hexdigest(), filesize, duration


def guess_mimetype(filepath):
    """Guess MIME type based on filename."""
    mime, _ = mimetypes.guess_type(filepath)
    return mime or 'application/octet-stream'


def guess_filetype(filepath, mimetype):
    """Guess file type based on filename and MIME type."""
    type_, subtype = mimetype.split('/')
    if filepath.endswith('.nii') or filepath.endswith('.nii.gz'):
        return 'nifti'
    elif filepath.endswith('_montage.zip'):
        return 'montage'
    elif type_ == 'text' and subtype in ['plain'] + [mt[2] for mt in MIMETYPES]:
        return 'text'
    else:
        return subtype


def format_timestamp(timestamp, tzname=None):
    timezone = pytz.timezone(tzname or 'UTC')
    return timezone.localize(timestamp).isoformat(), timezone.zone


def parse_timestamp(iso_timestamp):
    return dateutil.parser.parse(iso_timestamp)
