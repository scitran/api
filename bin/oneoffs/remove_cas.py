#!/usr/bin/env bash
import datetime
import logging
import os
import shutil
import uuid

from collections import Counter

from api import config
from api import files
from api import util


logging.basicConfig(
    format='%(asctime)s %(name)16.16s %(filename)24.24s %(lineno)5d:%(levelname)4.4s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.DEBUG,
)
log = logging.getLogger('remove_cas')


def path_from_hash(hash_):
    """
    create a filepath from a hash
    e.g.
    hash_ = v0-sha384-01b395a1cbc0f218
    will return
    v0/sha384/01/b3/v0-sha384-01b395a1cbc0f218
    """
    hash_version, hash_alg, actual_hash = hash_.split('-')
    first_stanza = actual_hash[0:2]
    second_stanza = actual_hash[2:4]
    path = (hash_version, hash_alg, first_stanza, second_stanza, hash_)
    return os.path.join(*path)


def get_files_by_prefix(document, prefix):
    for key in prefix.split('.'):
        document = document.get(key, {})
    return document


def copy_file(path, target_path):
    target_dir = os.path.dirname(target_path)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    shutil.copy(path, target_path)


def remove_cas():
    """
    Remove CAS logic, generate UUID for the files and rename them on the filesystem, make a copy of the file if more
    than one container using the same hash.
    """
    COLLECTIONS_PREFIXES = [('projects', 'files'),
                            ('acquisitions', 'files'),
                            ('analyses', 'files'),
                            ('sessions', 'files'),
                            ('sessions', 'subject.files')]

    _hashes = []
    _files = []

    for collection, prefix in COLLECTIONS_PREFIXES:
        cursor = config.db.get_collection(collection).find({})
        for document in cursor:
            for f in get_files_by_prefix(document, prefix):
                u = f.get('uuid', '')
                if u:
                    continue

                _hashes.append(f.get('hash', ''))
                f_dict = {
                    '_id': document.get('_id'),
                    'collection': collection,
                    'fileinfo': f,
                    'prefix': prefix
                }
                _files.append(f_dict)

    counter = Counter(_hashes)

    try:
        base = config.get_item('persistent', 'data_path')
        for f in _files:
            f_uuid = str(uuid.uuid4())
            f_path = os.path.join(base, path_from_hash(f['fileinfo']['hash']))
            f['uuid'] = f_uuid
            log.info('copy file %s to %s' % (f_path, util.path_from_uuid(f_uuid)))
            copy_file(f_path, os.path.join(base, util.path_from_uuid(f_uuid)))

            update_set = {
                f['prefix'] + '.$.modified': datetime.datetime.utcnow(),
                f['prefix'] + '.$.uuid': f_uuid
            }
            log.info('update file in mongo: %s' % update_set)
            # Update the file with the newly generated UUID
            config.db[f['collection']].find_one_and_update(
                {'_id': f['_id'], f['prefix'] + '.name': f['fileinfo']['name']},
                {'$set': update_set}
            )
            # Decrease the count of the current hash, so we will know when we can remove the original file
            counter[f['fileinfo']['hash']] -= 1

            if counter[f['fileinfo']['hash']] == 0:
                log.info('remove old file: %s' % f_path)
                os.remove(f_path)
    except Exception as e:
        log.exception(e)
        log.info('Rollback...')
        base = config.get_item('persistent', 'data_path')
        for f in _files:
            if f.get('uuid', ''):
                hash_path = os.path.join(base, path_from_hash(f['fileinfo']['hash']))
                uuid_path = util.path_from_uuid(f['uuid'])
                if os.path.exists(hash_path) and os.path.exists(uuid_path):
                    os.remove(uuid_path)
                elif os.path.exists(uuid_path):
                    copy_file(uuid_path, hash_path)
                    os.remove(uuid_path)
                config.db[f['collection']].find_one_and_update(
                    {'_id': f['_id'], f['prefix'] + '.name': f['fileinfo']['name']},
                    {'$unset': {f['prefix'] + '.$.uuid': ''}}
                )

    # Cleanup the empty folders
    log.info('Cleanup empty folders')
    for _dirpath, _, _ in os.walk(config.get_item('persistent', 'data_path'), topdown=False):
        if not (os.listdir(_dirpath) or config.get_item('persistent', 'data_path') == _dirpath):
            os.rmdir(_dirpath)


if __name__ == '__main__':
    remove_cas()

