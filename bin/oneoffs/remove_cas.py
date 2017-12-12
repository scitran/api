#!/usr/bin/env python
import datetime
import logging
import os
import shutil
import uuid

from collections import Counter

from api import config, files, util

log = logging.getLogger('remove_cas')
log.setLevel(logging.INFO)

class MigrationError(Exception):
    pass

def get_files_by_prefix(document, prefix):
    for key in prefix.split('.'):
        document = document.get(key, {})
    return document


def copy_file(path, target_path):
    target_dir = os.path.dirname(target_path)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    shutil.copy(path, target_path)


def cleanup_empty_folders():
    # Cleanup the empty folders
    log.info('Cleanup empty folders')
    for _dirpath, _, _ in os.walk(config.get_item('persistent', 'data_path'), topdown=False):
        if not (os.listdir(_dirpath) or config.get_item('persistent', 'data_path') == _dirpath):
            os.rmdir(_dirpath)


def remove_cas():
    """
    Remove CAS logic, generate UUID for the files and rename them on the filesystem, make a copy of the file if more
    than one container using the same hash.
    """
    COLLECTIONS_PREFIXES = [('projects', 'files'),
                            ('acquisitions', 'files'),
                            ('analyses', 'files'),
                            ('sessions', 'files'),
                            ('sessions', 'subject.files'),
                            ('collections', 'files')]

    _hashes = []
    _files = []

    for collection, prefix in COLLECTIONS_PREFIXES:
        cursor = config.db.get_collection(collection).find({})
        for document in cursor:
            for f in get_files_by_prefix(document, prefix):
                u = f.get('_id', '')
                if u:
                    continue

                _hashes.append(f.get('hash', ''))
                f_dict = {
                    'collection_id': document.get('_id'),
                    'collection': collection,
                    'fileinfo': f,
                    'prefix': prefix
                }
                _files.append(f_dict)

    counter = Counter(_hashes)

    try:
        base = config.get_item('persistent', 'data_path')
        for i, f in enumerate(_files):
            try:
                f_uuid = str(uuid.uuid4())
                f['_id'] = f_uuid
                f_path = os.path.join(base, util.path_from_hash(f['fileinfo']['hash']))
                log.debug('copy file %s to %s' % (f_path, util.path_from_uuid(f_uuid)))
                copy_file(f_path, files.get_file_abs_path(f_uuid))

                update_set = {
                    f['prefix'] + '.$.modified': datetime.datetime.utcnow(),
                    f['prefix'] + '.$._id': f_uuid
                }
                log.debug('update file in mongo: %s' % update_set)
                # Update the file with the newly generated UUID
                config.db[f['collection']].find_one_and_update(
                    {'_id': f['collection_id'], f['prefix'] + '.name': f['fileinfo']['name']},
                    {'$set': update_set}
                )

                # Decrease the count of the current hash, so we will know when we can remove the original file
                counter[f['fileinfo']['hash']] -= 1

                if counter[f['fileinfo']['hash']] == 0:
                    log.debug('remove old file: %s' % f_path)
                    os.remove(f_path)

                # Show progress
                if i % (len(_files) / 10) == 0:
                    log.info('Processed %s files of total %s files ...' % (i, len(_files)))

            except Exception as e:
                log.exception(e)
                raise MigrationError('Wasn\'t able to migrate the \'%s\' '
                                     'file in the \'%s\' collection (collection id: %s)' %
                                     (f['fileinfo']['name'], f['collection'], str(f['collection_id'])), e)
    except MigrationError as e:
        log.exception(e)
        log.info('Rollback...')
        base = config.get_item('persistent', 'data_path')
        for i, f in enumerate(_files):
            if f.get('_id', ''):
                hash_path = os.path.join(base, util.path_from_hash(f['fileinfo']['hash']))
                uuid_path = files.get_file_abs_path(f['_id'])
                if os.path.exists(hash_path) and os.path.exists(uuid_path):
                    os.remove(uuid_path)
                elif os.path.exists(uuid_path):
                    copy_file(uuid_path, hash_path)
                    os.remove(uuid_path)
                config.db[f['collection']].find_one_and_update(
                    {'_id': f['collection_id'], f['prefix'] + '.name': f['fileinfo']['name']},
                    {'$unset': {f['prefix'] + '.$._id': ''}}
                )
            # Show progress
            if i % (len(_files) / 10) == 0:
                log.info('Processed %s files of total %s files ...' % (i, len(_files)))
        cleanup_empty_folders()
        exit(1)

    cleanup_empty_folders()


if __name__ == '__main__':
    remove_cas()

