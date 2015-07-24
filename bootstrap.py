#!/usr/bin/env python
#
# @author:  Gunnar Schaefer

import logging
logging.basicConfig(
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
)
log = logging.getLogger('scitran.bootstrap')

import os
import json
import time
import pymongo
import hashlib
import argparse

import util


def dbinit(args):
    db = pymongo.MongoClient(args.db_uri).get_default_database()

    if args.force:
        db.client.drop_database(db)

    db.projects.create_index([('gid', 1), ('name', 1)])
    db.sessions.create_index('project')
    db.sessions.create_index('uid')
    db.acquisitions.create_index('session')
    db.acquisitions.create_index('uid')
    db.acquisitions.create_index('collections')
    db.authtokens.create_index('timestamp', expireAfterSeconds=600)
    db.uploads.create_index('timestamp', expireAfterSeconds=60)
    db.downloads.create_index('timestamp', expireAfterSeconds=60)
    # TODO jobs indexes
    # TODO review all indexes

    if args.json:
        with open(args.json) as json_dump:
            input_data = json.load(json_dump)
        if 'users' in input_data:
            db.users.insert(input_data['users'])
        if 'groups' in input_data:
            db.groups.insert(input_data['groups'])
        if 'drones' in input_data:
            db.drones.insert(input_data['drones'])
        for u in db.users.find():
            db.users.update({'_id': u['_id']}, {'$set': {'email_hash': hashlib.md5(u['email']).hexdigest()}})

    db.groups.update({'_id': 'unknown'}, {'$setOnInsert': {'name': 'Unknown', 'roles': []}}, upsert=True)

dbinit_desc = """
example:
./scripts/bootstrap.py dbinit mongodb://cnifs.stanford.edu/nims?replicaSet=cni -j nims_users_and_groups.json
"""


def sort(args):
    quarantine_path = os.path.join(args.sort_path, 'quarantine')
    if not os.path.exists(args.sort_path):
        os.makedirs(args.sort_path)
    if not os.path.exists(quarantine_path):
        os.makedirs(quarantine_path)
    log.info('initializing DB')
    db = pymongo.MongoClient(args.db_uri).get_default_database()
    log.info('inspecting %s' % args.path)
    files = []
    for dirpath, dirnames, filenames in os.walk(args.path):
        for filepath in [os.path.join(dirpath, fn) for fn in filenames if not fn.startswith('.')]:
            if not os.path.islink(filepath):
                files.append(filepath)
        dirnames[:] = [dn for dn in dirnames if not dn.startswith('.')] # need to use slice assignment to influence walk behavior
    file_cnt = len(files)
    log.info('found %d files to sort (ignoring symlinks and dotfiles)' % file_cnt)
    for i, filepath in enumerate(files):
        log.info('sorting     %s [%s] (%d/%d)' % (os.path.basename(filepath), util.hrsize(os.path.getsize(filepath)), i+1, file_cnt))
        hash_ = hashlib.sha1()
        if not args.quick:
            with open(filepath, 'rb') as fd:
                for chunk in iter(lambda: fd.read(2**20), ''):
                    hash_.update(chunk)
        datainfo = util.parse_file(filepath, hash_.hexdigest())
        if datainfo is None:
            util.quarantine_file(filepath, quarantine_path)
            log.info('quarantining %s (unparsable)' % os.path.basename(filepath))
        else:
            util.commit_file(db.acquisitions, None, datainfo, filepath, args.sort_path)

sort_desc = """
example:
./scripts/bootstrap.py sort mongodb://localhost/nims /tmp/data /tmp/sorted
"""


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(help='operation to perform')

dbinit_parser = subparsers.add_parser(
        name='dbinit',
        help='initialize database',
        description=dbinit_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
dbinit_parser.add_argument('-f', '--force', action='store_true', help='wipe out any existing data')
dbinit_parser.add_argument('-j', '--json', help='JSON file containing users and groups')
dbinit_parser.add_argument('db_uri', help='DB URI')
dbinit_parser.set_defaults(func=dbinit)

sort_parser = subparsers.add_parser(
        name='sort',
        help='sort all files in a dicrectory tree',
        description=sort_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
sort_parser.add_argument('-q', '--quick', action='store_true', help='omit computing of file checksums')
sort_parser.add_argument('db_uri', help='database URI')
sort_parser.add_argument('path', help='filesystem path to data')
sort_parser.add_argument('sort_path', help='filesystem path to sorted data')
sort_parser.set_defaults(func=sort)

args = parser.parse_args()
args.func(args)
