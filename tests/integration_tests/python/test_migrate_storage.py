import os
import sys

import fs.move
import fs.path
import pytest
import pymongo

from api import config, util
from bson.objectid import ObjectId


def move_file_to_legacy(src, dst):
    target_dir = fs.path.dirname(dst)
    if not config.legacy_fs.exists(target_dir):
        config.legacy_fs.makedirs(target_dir)
    fs.move.move_file(src_fs=config.fs, src_path=src,
                      dst_fs=config.legacy_fs, dst_path=dst)

@pytest.fixture(scope='function')
def migrate_storage(mocker):
    """Enable importing from `bin` and return `undelete.undelete`."""
    bin_path = os.path.join(os.getcwd(), 'bin', 'oneoffs')
    mocker.patch('sys.path', [bin_path] + sys.path)
    import migrate_storage
    return migrate_storage


@pytest.yield_fixture(scope='function')
def gears_to_migrate(api_db, as_admin, randstr, file_form):
    def gen_gear_meta(gear_name):
        return {'gear': {
            "version": '0.0.1',
            "config": {},
            "name": gear_name,
            "inputs": {
                "file": {
                    "base": "file",
                    "description": "Any image."
                }
            },
            "maintainer": "Test",
            "description": "Test",
            "license": "Other",
            "author": "Test",
            "url": "http://example.example",
            "label": "Test Gear",
            "flywheel": "0",
            "source": "http://example.example"
        }}

    gears = []

    gear_name_1 = randstr()

    file_name = '%s.tar.gz' % randstr()
    file_content = randstr()
    r = as_admin.post('/gears/temp', files=file_form((file_name, file_content), meta=gen_gear_meta(gear_name_1)))
    gear_id_1 = r.json()['_id']

    r = as_admin.get('/gears/' + gear_id_1)
    gear_json_1 = r.json()

    file_hash__1 = 'v0-' + gear_json_1['exchange']['rootfs-hash'].replace(':', '-')
    file_id_1 = gear_json_1['exchange']['rootfs-id']

    file_path = unicode(util.path_from_hash(file_hash__1))
    target_dir = fs.path.dirname(file_path)
    if not config.legacy_fs.exists(target_dir):
        config.legacy_fs.makedirs(target_dir)
    fs.move.move_file(src_fs=config.fs, src_path=util.path_from_uuid(file_id_1),
                      dst_fs=config.legacy_fs, dst_path=file_path)

    api_db['gears'].find_one_and_update(
        {'_id': ObjectId(gear_id_1)},
        {'$unset': {'exchange.rootfs-id': ''}})

    gears.append((gear_id_1, file_path))

    gear_name_2 = randstr()
    file_name = '%s.tar.gz' % randstr()
    file_content = randstr()
    r = as_admin.post('/gears/temp', files=file_form((file_name, file_content), meta=gen_gear_meta(gear_name_2)))
    gear_id_2 = r.json()['_id']


    r = as_admin.get('/gears/' + gear_id_2)
    gear_json_2 = r.json()

    file_id_2 = gear_json_2['exchange']['rootfs-id']

    file_path = unicode(util.path_from_uuid(file_id_2))
    target_dir = fs.path.dirname(file_path)
    if not config.legacy_fs.exists(target_dir):
        config.legacy_fs.makedirs(target_dir)
    fs.move.move_file(src_fs=config.fs, src_path=file_path,
                      dst_fs=config.legacy_fs, dst_path=file_path)

    gears.append((gear_id_2, file_path))

    yield gears

    # clean up
    gear_json_1 = api_db['gears'].find_one({'_id': ObjectId(gear_id_1)})
    gear_json_2 = api_db['gears'].find_one({'_id': ObjectId(gear_id_2)})
    files_to_delete = []
    files_to_delete.append(util.path_from_uuid(gear_json_1['exchange'].get('rootfs-id', '')))
    files_to_delete.append(util.path_from_uuid(gear_json_1['exchange'].get('rootfs-hash', '')))
    files_to_delete.append(util.path_from_uuid(gear_json_2['exchange'].get('rootfs-id', '')))

    for f_path in files_to_delete:
        try:
            config.fs.remove(f_path)
        except:
            pass

    api_db['gears'].delete_one({'_id': ObjectId(gear_id_1)})
    api_db['gears'].delete_one({'_id': ObjectId(gear_id_2)})

@pytest.yield_fixture(scope='function')
def files_to_migrate(data_builder, api_db, as_admin, randstr, file_form):
    # Create a project
    project_id = data_builder.create_project()

    files = []

    # Create a CAS file
    file_name_1 = '%s.csv' % randstr()
    file_content_1 = randstr()
    as_admin.post('/projects/' + project_id + '/files', files=file_form((file_name_1, file_content_1)))

    file_info = api_db['projects'].find_one(
        {'files.name': file_name_1}
    )['files'][0]
    file_id_1 = file_info['_id']
    file_hash_1 = file_info['hash']
    url_1 = '/projects/' + project_id + '/files/' + file_name_1

    api_db['projects'].find_one_and_update(
        {'files.name': file_name_1},
        {'$unset': {'files.$._id': ''}}
    )

    move_file_to_legacy(util.path_from_uuid(file_id_1), util.path_from_hash(file_hash_1))
    files.append((project_id, file_name_1, url_1, util.path_from_hash(file_hash_1)))
    # Create an UUID file
    file_name_2 = '%s.csv' % randstr()
    file_content_2 = randstr()
    as_admin.post('/projects/' + project_id + '/files', files=file_form((file_name_2, file_content_2)))

    file_info = api_db['projects'].find_one(
        {'files.name': file_name_2}
    )['files'][1]
    file_id_2 = file_info['_id']
    url_2 = '/projects/' + project_id + '/files/' + file_name_2

    move_file_to_legacy(util.path_from_uuid(file_id_2), util.path_from_uuid(file_id_2))
    files.append((project_id, file_name_2, url_2, util.path_from_uuid(file_id_2)))

    yield files

    # Clean up, get the files
    files = api_db['projects'].find_one(
        {'_id': ObjectId(project_id)}
    )['files']
    # Delete the files
    for f in files:
        try:
            config.fs.remove(util.path_from_uuid(f['_id']))
        except:
            pass

def test_migrate_containers(files_to_migrate, as_admin, migrate_storage):
    """Testing collection migration"""

    # get file storing by hash in legacy storage
    (_, _, url_1, file_path_1) = files_to_migrate[0]
    # get ile storing by uuid in legacy storage
    (_, _,url_2, file_path_2) = files_to_migrate[1]

    # get the ticket
    r = as_admin.get(url_1, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download the file
    assert as_admin.get(url_1, params={'ticket': ticket}).ok

    # get the ticket
    r = as_admin.get(url_2, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download the file
    assert as_admin.get(url_2, params={'ticket': ticket}).ok
    # run the migration
    migrate_storage.migrate_containers()

    # delete files from the legacy storage
    config.legacy_fs.remove(file_path_1)
    config.legacy_fs.remove(file_path_2)

    # get the files from the new filesystem
    # get the ticket
    r = as_admin.get(url_1, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download the file
    assert as_admin.get(url_1, params={'ticket': ticket}).ok

    # get the ticket
    r = as_admin.get(url_2, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download the file
    assert as_admin.get(url_2, params={'ticket': ticket}).ok

def test_migrate_containers_error(files_to_migrate, migrate_storage):
    """Testing that the migration script throws an exception if it couldn't migrate a file"""

    # get file storing by hash in legacy storage
    (_, _, url, file_path_1) = files_to_migrate[0]
    # get the other file, so we can clean up
    (_, _, _, file_path_2) = files_to_migrate[1]

    # delete the file
    config.legacy_fs.remove(file_path_1)

    with pytest.raises(migrate_storage.MigrationError):
        migrate_storage.migrate_containers()

    # clean up
    config.legacy_fs.remove(file_path_2)


def test_migrate_gears(gears_to_migrate, as_admin, migrate_storage):
    """Testing collection migration"""

    (gear_id_1, gear_file_path_1) = gears_to_migrate[0]
    (gear_id_2, gear_file_path_2) = gears_to_migrate[1]

    # get gears before migration
    assert as_admin.get('/gears/temp/' + gear_id_1).ok
    assert as_admin.get('/gears/temp/' + gear_id_2).ok

    # run migration
    migrate_storage.migrate_gears()

    # delete files from the legacy storage
    config.legacy_fs.remove(gear_file_path_1)
    config.legacy_fs.remove(gear_file_path_2)

    # get the files from the new filesystem
    assert as_admin.get('/gears/temp/' + gear_id_1).ok
    assert as_admin.get('/gears/temp/' + gear_id_2).ok


def test_migrate_gears_error(gears_to_migrate, migrate_storage):
    """Testing that the migration script throws an exception if it couldn't migrate a file"""

    # get file storing by hash in legacy storage
    (gear_id, gear_file_path_1) = gears_to_migrate[0]
    # get the other file, so we can clean up
    (_, gear_file_path_2) = gears_to_migrate[1]

    # delete the file
    config.legacy_fs.remove(gear_file_path_1)

    with pytest.raises(migrate_storage.MigrationError):
        migrate_storage.migrate_gears()

    # clean up
    config.legacy_fs.remove(gear_file_path_2)


def test_file_replaced_handling(files_to_migrate, migrate_storage, as_admin, file_form, api_db, mocker, caplog):

    origin_find_one_and_update = pymongo.collection.Collection.find_one_and_update

    def mocked(*args, **kwargs):
        self = args[0]
        filter = args[1]
        update = args[2]

        as_admin.post('/projects/' + project_id + '/files', files=file_form((file_name_1, 'new_content')))

        return origin_find_one_and_update(self, filter, update)


    with mocker.mock_module.patch.object(pymongo.collection.Collection, 'find_one_and_update', mocked):
        # get file storing by hash in legacy storage
        (project_id, file_name_1, url_1, file_path_1) = files_to_migrate[0]
        # get ile storing by uuid in legacy storage
        (_, file_name_2, url_2, file_path_2) = files_to_migrate[1]

        # run the migration
        migrate_storage.migrate_containers()

        file_1_id = api_db['projects'].find_one(
            {'files.name': file_name_1}
        )['files'][0]['_id']

        file_2_id = api_db['projects'].find_one(
            {'files.name': file_name_2}
        )['files'][1]['_id']

        assert config.fs.exists(util.path_from_uuid(file_1_id))
        assert config.fs.exists(util.path_from_uuid(file_2_id))

    assert any(log.message == 'Probably the following file has been updated during the migration and its hash is changed, cleaning up from the new filesystem' for log in caplog.records)


def test_migrate_analysis(files_to_migrate, as_admin, migrate_storage, default_payload, data_builder, file_form):
    """Testing analysis migration"""

    # get file storing by hash in legacy storage
    (project_id, file_name_1, url_1, file_path_1) = files_to_migrate[0]
    # get ile storing by uuid in legacy storage
    (_, _,url_2, file_path_2) = files_to_migrate[1]

    gear_doc = default_payload['gear']['gear']
    gear_doc['inputs'] = {
        'csv': {
            'base': 'file'
        }
    }
    gear = data_builder.create_gear(gear=gear_doc)

    # create project analysis (job) using project's file as input
    r = as_admin.post('/projects/' + project_id + '/analyses', params={'job': 'true'}, json={
        'analysis': {'label': 'test analysis job'},
        'job': {
            'gear_id': gear,
            'inputs': {
                'csv': {
                    'type': 'projects',
                    'id': project_id,
                    'name': file_name_1
                }
            },
            'tags': ['example']
        }
    })
    assert r.ok
    analysis_id1 = r.json()['_id']

    r = as_admin.get('/projects/' + project_id + '/analyses/' + analysis_id1)
    assert r.ok
    analysis_files1 = '/projects/' + project_id + '/analyses/' + analysis_id1 + '/files'

    # run the migration
    migrate_storage.migrate_containers()

    # delete files from the legacy storage
    config.legacy_fs.remove(file_path_1)
    config.legacy_fs.remove(file_path_2)

    # get the files from the new filesystem
    # get the ticket
    r = as_admin.get(url_1, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download the file
    assert as_admin.get(url_1, params={'ticket': ticket}).ok

    # get the ticket
    r = as_admin.get(url_2, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download the file
    assert as_admin.get(url_2, params={'ticket': ticket}).ok

    # get analysis download ticket for single file
    r = as_admin.get(analysis_files1 + '/' + file_name_1, params={'ticket': ''})
    assert r.ok
    ticket = r.json()['ticket']

    # download single analysis file w/ ticket
    r = as_admin.get(analysis_files1 + '/' + file_name_1, params={'ticket': ticket})
    assert r.ok

    r = as_admin.get('/projects/' + project_id + '/analyses/' + analysis_id1)
    assert r.ok
    input_file_id = r.json()['files'][0]['_id']

    r = as_admin.get('/projects/' + project_id)
    assert r.ok
    project_file_id = r.json()['files'][0]['_id']

    assert input_file_id == project_file_id
