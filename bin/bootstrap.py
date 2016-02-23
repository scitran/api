#!/usr/bin/env python

"""This script helps bootstrap users and data"""

import os
import json
import shutil
import hashlib
import logging
import zipfile
import argparse
import datetime
import requests

logging.basicConfig(
    format='%(asctime)s %(name)16.16s %(filename)24.24s %(lineno)5d:%(levelname)4.4s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.DEBUG,
)
log = logging.getLogger('scitran.bootstrap')

logging.getLogger('requests').setLevel(logging.WARNING) # silence Requests library


if 'SCITRAN_PERSISTENT_PATH' in os.environ and 'SCITRAN_PERSISTENT_DATA_PATH' not in os.environ:
    os.environ['SCITRAN_PERSISTENT_DATA_PATH'] = os.path.join(os.environ['SCITRAN_PERSISTENT_PATH'], 'data')


if 'SCITRAN_CORE_DRONE_SECRET' not in os.environ:
    log.error('SCITRAN_CORE_DRONE_SECRET not configured')
    sys.exit(1)

HTTP_HEADERS = {'X-SciTran-Auth': os.environ['SCITRAN_CORE_DRONE_SECRET'], 'User-Agent': 'SciTran Drone Bootstrapper'}
API_URL = 'https://localhost:8080/api'


def metadata_encoder(o):
    if isinstance(o, datetime.datetime):
        if o.tzinfo is None:
            o = pytz.timezone('UTC').localize(o)
        return o.isoformat()
    elif isinstance(o, datetime.tzinfo):
        return o.zone
    raise TypeError(repr(o) + ' is not JSON serializable')


def create_archive(content, arcname, metadata, filenames=None):
    path = content + '.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.comment = json.dumps(metadata, default=metadata_encoder)
        zf.write(content, arcname)
        for fn in filenames or os.listdir(content):
            zf.write(os.path.join(content, fn), os.path.join(arcname, fn))
    return path


def users(args):
    now = datetime.datetime.utcnow()
    with open(args.json) as json_dump:
        input_data = json.load(json_dump)
    log.info('bootstrapping users...')
    with requests.Session() as rs:
        rs.verify = not args.insecure
        rs.headers = HTTP_HEADERS
        for u in input_data.get('users', []):
            log.info('    ' + u['_id'])
            rs.post(API_URL + '/users', json=u)
    log.info('bootstrapping groups... foo')
    site_id = 'local' #config.get_item('site', 'id')
    for g in input_data.get('groups', []):
        log.info('    ' + g['_id'])
        roles = g.pop('roles')
        rs.post(API_URL + '/groups' , json=g)
        for r in roles:
            r.setdefault('site', site_id)
            rs.post(API_URL + '/groups/' + g['_id'] + '/roles' , json=r)
    log.info('bootstrapping complete')

users_desc = """
example:
./bin/bootstrap.py users users_and_groups.json
"""


# TODO pattern should be: zip to tempdir, upload, next
def data(args):
    log.info('Inspecting  %s' % args.path)
    files = []
    for dirpath, dirnames, filenames in os.walk(args.path):
        dirnames[:] = [dn for dn in dirnames if not dn.startswith('.')] # use slice assignment to influence walk
        if not dirnames and filenames:
            for metadata_file in filenames:
                if metadata_file.lower() == 'metadata.json':
                    filenames.remove(metadata_file)
                    break
            else:
                metadata_file = None
            if not metadata_file:
                log.warning('Skipping    %s: No metadata found' % dirpath)
                continue
            with open(os.path.join(dirpath, metadata_file)) as fd:
                try:
                    metadata = json.load(fd)
                except ValueError:
                    log.warning('Skipping    %s: Invalid metadata' % dirpath)
                    continue
            # FIXME need schema validation
            log.info('Packaging   %s' % dirpath)
            filepath = create_archive(dirpath, os.path.basename(dirpath), metadata, filenames)
            files.append(filepath)
    file_cnt = len(files)
    log.info('Found %d files to sort (ignoring symlinks and dotfiles)' % file_cnt)
    for i, filepath in enumerate(files):
        log.info('Loading     %s [%s] (%d/%d)' % (os.path.basename(filepath), util.hrsize(os.path.getsize(filepath)), i+1, file_cnt))
        hash_ = hashlib.sha384()
        size = os.path.getsize(filepath)
        try:
            metadata = json.loads(zipfile.ZipFile(filepath).comment)
            if not metadata:
                raise ValueError('Invalid metadata')
        except ValueError:
            log.warning('Skipping    %s: Invalid metadata' % os.path.basename(filepath))
            continue
        target, file_ = reaperutil.create_container_hierarchy(metadata)
        with open(filepath, 'rb') as fd:
            for chunk in iter(lambda: fd.read(2**20), ''):
                hash_.update(chunk)
        computed_hash = 'v0-sha384-' + hash_.hexdigest()
        destpath = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(computed_hash))
        dir_destpath = os.path.dirname(destpath)
        filename = os.path.basename(filepath)
        if not os.path.exists(dir_destpath):
            os.makedirs(dir_destpath)
        if args.copy:
            shutil.copyfile(filepath, destpath)
        else:
            shutil.move(filepath, destpath)
        created = modified = datetime.datetime.utcnow()
        fileinfo = {
            'name': filename,
            'size': size,
            'hash': computed_hash,
            'type': 'dicom', # we are only bootstrapping dicoms at the moment
            'created': created,
            'modified': modified,
            'mimetype': util.guess_mimetype(filename),
        }
        fileinfo.update(file_)
        target.add_file(fileinfo)
        rules.create_jobs(config.db, target.container, 'acquisition', fileinfo)


data_desc = """
example:
./bin/bootstrap.py data /tmp/data
"""


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(help='operation to perform')

users_parser = subparsers.add_parser(
        name='users',
        help='bootstrap users and groups',
        description=users_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
users_parser.add_argument('json', help='JSON file containing users and groups')
users_parser.set_defaults(func=users)

data_parser = subparsers.add_parser(
        name='data',
        help='bootstrap files in a dicrectory tree',
        description=data_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
data_parser.add_argument('path', help='filesystem path to data')
data_parser.set_defaults(func=data)

parser.add_argument('-i', '--insecure', action='store_true', help='do not verify SSL connections')
args = parser.parse_args()

if args.insecure:
    requests.packages.urllib3.disable_warnings()

args.func(args)
