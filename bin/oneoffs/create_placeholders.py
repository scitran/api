#!/usr/bin/env python
import logging
import os
import shutil

from api import util, config

log = logging.getLogger('create_placeholders')
log.setLevel(logging.INFO)


def get_files_by_prefix(document, prefix):
    for key in prefix.split('.'):
        document = document.get(key, {})
    return document


def create_placeholders():
    """
    Create placeholder files to help testing a system using sanitized customer DBs without the corresponding data files.
    """
    COLLECTIONS_PREFIXES = [('projects', 'files'),
                            ('acquisitions', 'files'),
                            ('analyses', 'files'),
                            ('sessions', 'files'),
                            ('sessions', 'subject.files')]

    _files = []

    for collection, prefix in COLLECTIONS_PREFIXES:
        cursor = config.db.get_collection(collection).find({})
        for document in cursor:
            for f in get_files_by_prefix(document, prefix):
                f_dict = {
                    'collection_id': document.get('_id'),
                    'collection': collection,
                    'fileinfo': f,
                    'prefix': prefix
                }
                _files.append(f_dict)

    base = config.get_item('persistent', 'data_path')
    for i, f in enumerate(_files):
        f_path = os.path.join(base, util.path_from_hash(f['fileinfo']['hash']))

        target_dir = os.path.dirname(f_path)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        with open(f_path, 'w') as placeholder:
            placeholder.write('%s %s' % (f_path, f['fileinfo']['size']))

        # Show progress
        if i % (len(_files) / 10) == 0:
            log.info('Processed %s files of total %s files ...' % (i, len(_files)))


if __name__ == '__main__':
    create_placeholders()


