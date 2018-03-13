#!/usr/bin/env python
import argparse
import datetime
import logging
import os
import uuid

import fs.path
import fs.move

from api import config, util

log = logging.getLogger('migrate_storage')
log.setLevel(logging.INFO)


class MigrationError(Exception):
    pass


def get_files_by_prefix(document, prefix):
    for key in prefix.split('.'):
        document = document.get(key, {})
    return document


def show_progress(current_index, total_files):
    if current_index % (total_files / 10 + 1) == 0:
        log.info('Processed %s files of total %s files ...' % (current_index, total_files))


def cleanup_empty_folders():
    log.info('Cleanup empty folders')

    for _dirpath, _, _ in os.walk(config.get_item('persistent', 'data_path'), topdown=False):
        if not (os.listdir(_dirpath) or config.get_item('persistent', 'data_path') == _dirpath):
            os.rmdir(_dirpath)


def get_containers_files(containers_prefixes):
    _files = []

    for container, prefix in containers_prefixes:
        cursor = config.db.get_collection(container).find({})
        for document in cursor:
            for f in get_files_by_prefix(document, prefix):
                f_dict = {
                    'container_id': document.get('_id'),
                    'container': container,
                    'fileinfo': f,
                    'prefix': prefix
                }
                _files.append(f_dict)

    return _files


def get_gears_files():
    cursor = config.db.get_collection('gears').find({})
    _files = []

    for document in cursor:
        if document.get('exchange', {}).get('git-commit', '') == 'local':
            f_dict = {
                'gear_id': document['_id'],
                'gear_name': document['gear']['name'],
                'exchange': document['exchange']
            }
            _files.append(f_dict)

    return _files


def migrate_file(f):
    try:
        file_id = f['fileinfo'].get('_id', '')
        if file_id:
            file_path = util.path_from_uuid(file_id)
            if not config.fs.isfile(file_path):
                """Copy file from legacy to new storage"""

                log.debug('copy file between the legacy and new storage: %s' % file_path)

                dst_dir = fs.path.dirname(file_path)
                config.fs.makedirs(dst_dir, recreate=True)
                fs.move.copy_file(src_fs=config.legacy_fs, src_path=file_path, dst_fs=config.fs, dst_path=file_path)
        else:
            """generate uuuid, set the id field and copy the file"""
            file_id = str(uuid.uuid4())
            f_old_path = util.path_from_hash(f['fileinfo']['hash'])
            f_new_path = util.path_from_uuid(file_id)

            log.debug('copy file %s to %s' % (f_old_path, f_new_path))

            dst_dir = fs.path.dirname(f_new_path)
            config.fs.makedirs(dst_dir, recreate=True)
            fs.move.copy_file(src_fs=config.legacy_fs, src_path=f_old_path, dst_fs=config.fs, dst_path=f_new_path)

            update_set = {
                f['prefix'] + '.$.modified': datetime.datetime.utcnow(),
                f['prefix'] + '.$._id': file_id
            }
            log.debug('update file in mongo: %s' % update_set)
            # Update the file with the newly generated UUID
            updated_doc = config.db[f['container']].find_one_and_update(
                {'_id': f['container_id'],
                 f['prefix'] + '.name': f['fileinfo']['name'],
                 f['prefix'] + '.hash': f['fileinfo']['hash']},
                {'$set': update_set}
            )

            if not updated_doc:
                log.info('Probably the following file has been updated during the migration '
                         'and its hash is changed, cleaning up from the new filesystem')
                config.fs.remove(f_new_path)

    except Exception as e:
        log.exception(e)
        raise MigrationError('Wasn\'t able to migrate the \'%s\' '
                             'file in the \'%s\' container (container id: %s)' %
                             (f['fileinfo']['name'], f['container'], str(f['container_id'])), e)


def migrate_containers():
    log.info('Migrate container (projects, acquisitions, sessions, subject, collections) files...')

    container_files = get_containers_files([('projects', 'files'),
                                            ('acquisitions', 'files'),
                                            ('sessions', 'files'),
                                            ('sessions', 'subject.files'),
                                            ('collections', 'files')])

    for i, f in enumerate(container_files):
        migrate_file(f)
        show_progress(i + 1, len(container_files))

    log.info('Migrate analysis files...')
    # Refresh the list of container files
    container_files = get_containers_files([('projects', 'files'),
                                            ('acquisitions', 'files'),
                                            ('sessions', 'files'),
                                            ('sessions', 'subject.files'),
                                            ('collections', 'files')])
    analysis_files = get_containers_files([('analyses', 'files')])

    for i, f in enumerate(analysis_files):
        match = [cf for cf in container_files if cf['fileinfo']['hash'] == f['fileinfo']['hash'] and cf['fileinfo'].get('_id')]
        # The file is already migrated
        if len(match) > 0 and not f['fileinfo'].get('_id'):
            update_set = {
                f['prefix'] + '.$.modified': match[0]['fileinfo']['modified'],
                f['prefix'] + '.$._id': match[0]['fileinfo']['_id']
            }
            log.debug('update file in mongo: %s' % update_set)
            # Update the file with the newly generated UUID
            config.db[f['container']].find_one_and_update(
                {'_id': f['container_id'],
                 f['prefix'] + '.name': f['fileinfo']['name'],
                 f['prefix'] + '.hash': f['fileinfo']['hash']},
                {'$set': update_set}
            )
        else:
            migrate_file(f)
        show_progress(i + 1, len(analysis_files))


def migrate_gears():
    log.info('Migrate gears...')

    _files = get_gears_files()

    for i, f in enumerate(_files):
        try:
            file_id = f['exchange'].get('rootfs-id', '')
            if file_id:
                file_path = util.path_from_uuid(file_id)
                if not config.fs.isfile(file_path):
                    """Copy file from legacy to new storage"""

                    log.debug('copy file between the legacy and new storage: %s' % file_path)

                    dst_dir = fs.path.dirname(file_path)
                    config.fs.makedirs(dst_dir, recreate=True)
                    fs.move.copy_file(src_fs=config.legacy_fs, src_path=file_path, dst_fs=config.fs, dst_path=file_path)
            else:
                file_id = str(uuid.uuid4())
                file_hash = 'v0-' + f['exchange']['rootfs-hash'].replace(':', '-')
                f_old_path = util.path_from_hash(file_hash)
                f_new_path = util.path_from_uuid(file_id)

                log.debug('copy file %s to %s' % (f_old_path, f_new_path))

                dst_dir = fs.path.dirname(f_new_path)
                config.fs.makedirs(dst_dir, recreate=True)
                fs.move.copy_file(src_fs=config.legacy_fs, src_path=f_old_path, dst_fs=config.fs, dst_path=f_new_path)

                update_set = {
                    'modified': datetime.datetime.utcnow(),
                    'exchange.rootfs-id': file_id
                }

                log.debug('update file in mongo: %s' % update_set)
                # Update the gear with the newly generated UUID
                config.db['gears'].find_one_and_update(
                    {'_id': f['gear_id']},
                    {'$set': update_set}
                )

                show_progress(i + 1, len(_files))
        except Exception as e:
            log.exception(e)
            raise MigrationError('Wasn\'t able to migrate the \'%s\' gear (gear id: %s)' %
                                 (f['gear_name'], f['gear_id']), e)


def migrate_storage():
    """
    Remove CAS logic, generate UUID for the files and move the files from the lagacy storage to the new one.
    """

    parser = argparse.ArgumentParser(prog='Migrate storage')
    parser.add_argument('--containers', action='store_true', help='Migrate containers')
    parser.add_argument('--gears', action='store_true', help='Migrate gears')
    parser.add_argument('--delete-files', action='store_true', help='Delete files from legacy storage')


    args = parser.parse_args()

    try:
        if not (args.containers or args.gears):
            migrate_containers()
            migrate_gears()

        if args.containers:
            migrate_containers()

        if args.gears:
            migrate_gears()

        if args.delete_files:
            config.legacy_fs.removetree('/')

    except MigrationError as e:
        log.exception(e)
        exit(1)
    finally:
        cleanup_empty_folders()
        pass


if __name__ == '__main__':
    migrate_storage()
