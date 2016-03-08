#!/usr/bin/env python

"""This script helps bootstrap users and data"""

import os
import json
import shutil
import hashlib
import zipfile
import argparse
import datetime
import requests


from api.dao import reaperutil
from api import util
from api import rules
from api import config

log = config.log


def clean(args):
    config.db.client.drop_database(config.db)

clean_desc = """
example:
./bin/bootstrap.py clean
"""


def users(args):
    now = datetime.datetime.utcnow()
    with open(args.json) as json_dump:
        input_data = json.load(json_dump)
    log.info('bootstrapping users...')
    with requests.Session() as rs:
        rs.params = {'d': '404'}
        for u in input_data.get('users', []):
            log.info('    ' + u['_id'])
            u['created'] = now
            u['modified'] = now
            u.setdefault('email', u['_id'])
            u.setdefault('preferences', {})
            gravatar = 'https://gravatar.com/avatar/' + hashlib.md5(u['email']).hexdigest() + '?s=512'
            if rs.head(gravatar):
                u.setdefault('avatar', gravatar)
            u.setdefault('avatars', {})
            u['avatars'].setdefault('gravatar', gravatar)
            config.db.users.update_one({'_id': u['_id']}, {'$setOnInsert': u}, upsert=True)
    log.info('bootstrapping groups...')
    site_id = config.get_item('site', 'id')
    for g in input_data.get('groups', []):
        log.info('    ' + g['_id'])
        g['created'] = now
        g['modified'] = now
        for r in g['roles']:
            r.setdefault('site', site_id)
        config.db.groups.update_one({'_id': g['_id']}, {'$setOnInsert': g}, upsert=True)
    log.info('bootstrapping drones...')
    for d in input_data.get('drones', []):
        log.info('    ' + d['_id'])
        d['created'] = now
        d['modified'] = now
        config.db.drones.update_one({'_id': d['_id']}, {'$setOnInsert': d}, upsert=True)
    log.info('bootstrapping complete')

users_desc = """
example:
./bin/bootstrap.py users users_and_groups.json
"""


def data(args):
    log.info('inspecting %s' % args.path)
    files = []
    for dirpath, dirnames, filenames in os.walk(args.path):
        for filepath in [os.path.join(dirpath, fn) for fn in filenames if not fn.startswith('.')]:
            if not os.path.islink(filepath) and filepath.endswith('.zip'):
                files.append(filepath)
        dirnames[:] = [dn for dn in dirnames if not dn.startswith('.')] # need to use slice assignment to influence walk behavior
    file_cnt = len(files)
    log.info('found %d files to sort (ignoring symlinks and dotfiles)' % file_cnt)
    for i, filepath in enumerate(files):
        log.info('Loading     %s [%s] (%d/%d)' % (os.path.basename(filepath), util.hrsize(os.path.getsize(filepath)), i+1, file_cnt))
        hash_ = hashlib.sha384()
        size = os.path.getsize(filepath)
        try:
            metadata = json.loads(zipfile.ZipFile(filepath).comment)
        except ValueError as e:
            log.warning(str(e))
            continue
        container = reaperutil.create_container_hierarchy(metadata)
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
            'modified': modified
        }
        container.add_file(fileinfo)
        rules.create_jobs(config.db, container.acquisition, 'acquisition', fileinfo)


data_desc = """
example:
./bin/bootstrap.py data /tmp/data
"""


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(help='operation to perform')

clean_parser = subparsers.add_parser(
        name='clean',
        help='reset database to clean state',
        description=clean_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
clean_parser.set_defaults(func=clean)

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
data_parser.add_argument('-c', '--copy', action='store_true', help='copy data instead of moving it')
data_parser.add_argument('path', help='filesystem path to data')
data_parser.set_defaults(func=data)

args = parser.parse_args()
args.func(args)
