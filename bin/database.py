#!/usr/bin/env python

import argparse
import bson
import copy
import datetime
import dateutil.parser
import json
import logging
import multiprocessing
import os
import re
import sys
import time

from api import config
from api import util
from api.dao import containerutil
from api.dao.containerstorage import ProjectStorage
from api.jobs.jobs import Job
from api.jobs import gears
from api.types import Origin
from api.jobs import batch

CURRENT_DATABASE_VERSION = 43 # An int that is bumped when a new schema change is made

def get_db_version():

    version = config.get_version()
    if version is None:
        # Attempt to find db version at old location
        version = config.db.version.find_one({'_id': 'version'})
    if version is None or version.get('database') is None:
        return 0
    return version.get('database')

def confirm_schema_match():
    """
    Checks version of database schema

    Returns (0)  if DB schema version matches requirements.
    Returns (42) if DB schema version does not match
                 requirements and can be upgraded.
    Returns (43) if DB schema version does not match
                 requirements and cannot be upgraded,
                 perhaps because code is at lower version
                 than the DB schema version.
    """

    db_version = get_db_version()
    if not isinstance(db_version, int) or db_version > CURRENT_DATABASE_VERSION:
        logging.error('The stored db schema version of %s is incompatible with required version %s',
                       str(db_version), CURRENT_DATABASE_VERSION)
        sys.exit(43)
    elif db_version < CURRENT_DATABASE_VERSION:
        sys.exit(42)
    else:
        sys.exit(0)

def getMonotonicTime():
    # http://stackoverflow.com/a/7424304
    return os.times()[4]

def process_cursor(cursor, closure, context = None):
    """
    Given an iterable (say, a mongo cursor) and a closure, call that closure in parallel over the iterable.
    Call order is undefined. Currently launches N python process workers, where N is the number of vcpu cores.

    Useful for upgrades that need to touch each document in a database, and don't need an iteration order.

    Your closure MUST return True on success. Anything else is logged and treated as a failure.
    A closure that throws an exception will fail the upgrade immediately.
    """

    begin = getMonotonicTime()

    # cores = multiprocessing.cpu_count()
    # pool = multiprocessing.Pool(cores)
    # logging.info('Iterating over cursor with ' + str(cores) + ' workers')

    # # Launch all work, iterating over the cursor
    # # Note that this creates an array of n multiprocessing.pool.AsyncResults, where N is table size.
    # # Memory usage concern in the future? Doesn't seem to be an issue with ~120K records.
    # # Could be upgraded later with some yield trickery.
    # results = [pool.apply_async(closure, (document,)) for document in cursor]

    # # Read the results back, presumably in order!
    # failed = False
    # for res in results:
    # 	result = res.get()
    # 	if result != True:
    # 		failed = True
    # 		logging.info('Upgrade failed: ' + str(result))

    # logging.info('Waiting for workers to complete')
    # pool.close()
    # pool.join()

    logging.info('Proccessing {} items in cursor ...'.format(cursor.count()))

    failed = False
    cursor_size = cursor.count()
    cursor_index = 0.0
    next_percent = 5.0
    percent_increment = 5
    if(cursor_size < 20):
        next_percent = 25.0
        percent_increment = 25
    if(cursor_size < 4):
        next_percent = 50.0
        percent_increment = 50
    for document in cursor:
        if 100 * (cursor_index / cursor_size) >= next_percent:
            logging.info('{} percent complete ...'.format(next_percent))
            next_percent = next_percent + percent_increment
        if context == None:
            result = closure(document)
        else:
            result = closure(document, context)
        cursor_index = cursor_index + 1
        if result != True:
            failed = True
            logging.info('Upgrade failed: ' + str(result))

    if failed is True:
        msg = 'Worker pool experienced one or more failures. See above logs.'
        logging.info(msg)
        raise Exception(msg)

    end = getMonotonicTime()
    elapsed = end - begin
    logging.info('Parallel cursor iteration took ' + ('%.2f' % elapsed))

def upgrade_to_1():
    """
    scitran/core issue #206

    Initialize db version to 1
    """
    config.db.singletons.insert_one({'_id': 'version', 'database': 1})

def upgrade_to_2():
    """
    scitran/core PR #236

    Set file.origin.name to id if does not exist
    Set file.origin.method to '' if does not exist
    """

    def update_file_origins(cont_list, cont_name):
        for container in cont_list:
            updated_files = []
            for file in container.get('files', []):
                origin = file.get('origin')
                if origin is not None:
                    if origin.get('name', None) is None:
                        file['origin']['name'] = origin['id']
                    if origin.get('method', None) is None:
                        file['origin']['method'] = ''
                updated_files.append(file)

            query = {'_id': container['_id']}
            update = {'$set': {'files': updated_files}}
            result = config.db[cont_name].update_one(query, update)

    query = {'$and':[{'files.origin.name': { '$exists': False}}, {'files.origin.id': { '$exists': True}}]}

    update_file_origins(config.db.collections.find(query), 'collections')
    update_file_origins(config.db.projects.find(query), 'projects')
    update_file_origins(config.db.sessions.find(query), 'sessions')
    update_file_origins(config.db.acquisitions.find(query), 'acquisitions')

def upgrade_to_3():
    """
    scitran/core issue #253

    Set first user with admin permissions found as curator if one does not exist
    """
    query = {'curator': {'$exists': False}, 'permissions.access': 'admin'}
    projection = {'permissions.$':1}
    collections = config.db.collections.find(query, projection)
    for coll in collections:
        admin = coll['permissions'][0]['_id']
        query = {'_id': coll['_id']}
        update = {'$set': {'curator': admin}}
        config.db.collections.update_one(query, update)

def upgrade_to_4():
    """
    scitran/core issue #263

    Add '_id' field to session.subject
    Give subjects with the same code and project the same _id
    """

    pipeline = [
        {'$match': { 'subject._id': {'$exists': False}}},
        {'$group' : { '_id' : {'pid': '$project', 'code': '$subject.code'}, 'sids': {'$push': '$_id' }}}
    ]

    subjects = config.db.command('aggregate', 'sessions', pipeline=pipeline)
    for subject in subjects['result']:

        # Subjects without a code and sessions without a subject
        # will be returned grouped together, but all need unique IDs
        if subject['_id'].get('code') is None:
            for session_id in subject['sids']:
                subject_id = bson.ObjectId()
                config.db.sessions.update_one({'_id': session_id},{'$set': {'subject._id': subject_id}})
        else:
            subject_id = bson.ObjectId()
            query = {'_id': {'$in': subject['sids']}}
            update = {'$set': {'subject._id': subject_id}}
            config.db.sessions.update_many(query, update)

def upgrade_to_5():
    """
    scitran/core issue #279

    Ensure all sessions and acquisitions have the same perms as their project
    Bug(#278) discovered where changing a session's project did not update acquisition perms
    """

    projects = config.db.projects.find({})
    for p in projects:
        perms = p.get('permissions', [])

        session_ids = [s['_id'] for s in config.db.sessions.find({'project': p['_id']}, [])]

        config.db.sessions.update_many({'project': p['_id']}, {'$set': {'permissions': perms}})
        config.db.acquisitions.update_many({'session': {'$in': session_ids}}, {'$set': {'permissions': perms}})

def upgrade_to_6():
    """
    scitran/core issue #277

    Ensure all collection modified dates are ISO format
    Bug fixed in 6967f23
    """

    colls = config.db.collections.find({'modified': {'$type': 2}}) # type string
    for c in colls:
        fixed_mod = dateutil.parser.parse(c['modified'])
        config.db.collections.update_one({'_id': c['_id']}, {'$set': {'modified': fixed_mod}})

def upgrade_to_7():
    """
    scitran/core issue #270

    Add named inputs and specified destinations to jobs.

    Before:
    {
        "input" : {
            "container_type" : "acquisition",
            "container_id" : "572baf4e23dcb77ebbe06b3f",
            "filename" : "1_1_dicom.zip",
            "filehash" : "v0-sha384-422bd115d21585d1811d42cd99f1cf0a8511a4b377dd2deeaa1ab491d70932a051926ed99815a75142ad0815088ed009"
        }
    }

    After:
    {
        "inputs" : {
            "dicom" : {
                "container_type" : "acquisition",
                "container_id" : "572baf4e23dcb77ebbe06b3f",
                "filename" : "1_1_dicom.zip"
            }
        },
        "destination" : {
            "container_type" : "acquisition",
            "container_id" : "572baf4e23dcb77ebbe06b3f"
        }
    }
    """

    # The infrastructure runs this upgrade script before populating manifests.
    # For this reason, this one-time script does NOT pull manifests to do the input-name mapping, instead relying on a hard-coded alg name -> input name map.
    # If you have other gears in your system at the time of upgrade, you must add that mapping here.
    input_name_for_gear = {
        'dcm_convert': 'dicom',
        'qa-report-fmri': 'nifti',
        'dicom_mr_classifier': 'dicom',
    }

    jobs = config.db.jobs.find({'input': {'$exists': True}})

    for job in jobs:
        gear_name = job['algorithm_id']
        input_name = input_name_for_gear[gear_name]

        # Move single input to named input map
        input_ = job['input']
        input_.pop('filehash', None)
        inputs = { input_name: input_ }

        # Destination is required, and (for these jobs) is always the same container as the input
        destination = copy.deepcopy(input_)
        destination.pop('filename', None)

        config.db.jobs.update_one(
            {'_id': job['_id']},
            {
                '$set': {
                    'inputs': inputs,
                    'destination': destination
                },
                '$unset': {
                    'input': ''
                }
            }
        )

def upgrade_to_8():
    """
    scitran/core issue #291

    Migrate config, version, gears and rules to singletons collection
    """

    colls = config.db.collection_names()
    to_be_removed = ['version', 'config', 'static']
    # If we are in a bad state (singletons exists but so do any of the colls in to be removed)
    # remove singletons to try again
    if 'singletons' in colls and set(to_be_removed).intersection(set(colls)):
        config.db.drop_collection('singletons')

    if 'singletons' not in config.db.collection_names():
        static = config.db.static.find({})
        if static.count() > 0:
            config.db.singletons.insert_many(static)
        config.db.singletons.insert(config.db.version.find({}))

        configs = config.db.config.find({'latest': True},{'latest':0})
        if configs.count() == 1:
            c = configs[0]
            c['_id'] = 'config'
            config.db.singletons.insert_one(c)

        for c in to_be_removed:
            if c in config.db.collection_names():
                config.db.drop_collection(c)

def upgrade_to_9():
    """
    scitran/core issue #292

    Remove all session and acquisition timestamps that are empty strings
    """

    config.db.acquisitions.update_many({'timestamp':''}, {'$unset': {'timestamp': ''}})
    config.db.sessions.update_many({'timestamp':''}, {'$unset': {'timestamp': ''}})

def upgrade_to_10():
    """
    scitran/core issue #301

    Makes the following key renames, all in the jobs table.
    FR is a FileReference, CR is a ContainerReference:

    job.algorithm_id  --> job.name

    FR.container_type --> type
    FR.container_id   --> id
    FR.filename       --> name

    CR.container_type --> type
    CR.container_id   --> id
    """

    def switch_keys(doc, x, y):
        doc[y] = doc[x]
        doc.pop(x, None)


    jobs = config.db.jobs.find({'destination.container_type': {'$exists': True}})

    for job in jobs:
        switch_keys(job, 'algorithm_id', 'name')

        for key in job['inputs'].keys():
            inp = job['inputs'][key]

            switch_keys(inp, 'container_type', 'type')
            switch_keys(inp, 'container_id',   'id')
            switch_keys(inp, 'filename',       'name')


        dest = job['destination']
        switch_keys(dest, 'container_type', 'type')
        switch_keys(dest, 'container_id',   'id')

        config.db.jobs.update(
            {'_id': job['_id']},
            job
        )

def upgrade_to_11():
    """
    scitran/core issue #362

    Restructures job objects' `inputs` field from a dict with arbitrary keys
    into a list where the key becomes the field `input`
    """

    jobs = config.db.jobs.find({'inputs.type': {'$exists': False}})

    for job in jobs:

        inputs_arr = []
        for key, inp in job['inputs'].iteritems():
            inp['input'] = key
            inputs_arr.append(inp)

        config.db.jobs.update(
            {'_id': job['_id']},
            {'$set': {'inputs': inputs_arr}}
        )

def upgrade_to_12():
    """
    scitran/core PR #372

    Store job inputs on job-based analyses
    """

    sessions = config.db.sessions.find({'analyses.job': {'$exists': True}})

    for session in sessions:
        for analysis in session.get('analyses'):
            if analysis.get('job'):
                job = Job.get(analysis['job'])
                files = analysis.get('files', [])
                files[:] = [x for x in files if x.get('output')] # remove any existing inputs and insert fresh

                for i in getattr(job, 'inputs', {}):
                    fileref = job.inputs[i]
                    contref = containerutil.create_containerreference_from_filereference(job.inputs[i])
                    file_ = contref.find_file(fileref.name)
                    if file_:
                        file_['input'] = True
                        files.append(file_)

                q = {'analyses._id': analysis['_id']}
                u = {'$set': {'analyses.$.job': job.id_, 'analyses.$.files': files}}
                config.db.sessions.update_one(q, u)

def upgrade_to_13():
    """
    scitran/core PR #403

    Clear schema path from db config in order to set abs path to files
    """
    config.db.singletons.find_one_and_update(
        {'_id': 'config', 'persistent.schema_path': {'$exists': True}},
        {'$unset': {'persistent.schema_path': ''}})

def upgrade_to_14():
    """schema_path is no longer user configurable"""
    config.db.singletons.find_one_and_update(
        {'_id': 'config', 'persistent.schema_path': {'$exists': True}},
        {'$unset': {'persistent.schema_path': ''}})

def upgrade_to_15():
    """
    scitran/pull issue #417

    First remove all timestamps that are empty or not mongo date or string format.
    Then attempt to convert strings to dates, removing those that cannot be converted.
    Mongo $type maps: String = 2, Date = 9
    """
    query = {}
    query['$or'] = [
                    {'timestamp':''},
                    {'$and': [
                        {'timestamp': {'$exists': True}},
                        {'timestamp': {'$not': {'$type':2}}},
                        {'timestamp': {'$not': {'$type':9}}}
                    ]}
                ]
    unset = {'$unset': {'timestamp': ''}}

    config.db.sessions.update_many(query, unset)
    config.db.acquisitions.update_many(query, unset)

    query =  {'$and': [
                {'timestamp': {'$exists': True}},
                {'timestamp': {'$type':2}}
            ]}
    sessions = config.db.sessions.find(query)
    for s in sessions:
        try:
            fixed_timestamp = dateutil.parser.parse(s['timestamp'])
        except:
            config.db.sessions.update_one({'_id': s['_id']}, {'$unset': {'timestamp': ''}})
            continue
        config.db.sessions.update_one({'_id': s['_id']}, {'$set': {'timestamp': fixed_timestamp}})

    acquisitions = config.db.acquisitions.find(query)
    for a in acquisitions:
        try:
            fixed_timestamp = dateutil.parser.parse(a['timestamp'])
        except:
            config.db.sessions.update_one({'_id': a['_id']}, {'$unset': {'timestamp': ''}})
            continue
        config.db.sessions.update_one({'_id': a['_id']}, {'$set': {'timestamp': fixed_timestamp}})

def upgrade_to_16():
    """
    Fixes file.size sometimes being a floating-point rather than integer.
    """

    acquisitions = config.db.acquisitions.find({'files.size': {'$type': 'double'}})
    for x in acquisitions:
        for y in x.get('files', []):
            if y.get('size'):
                y['size'] = int(y['size'])
        config.db.acquisitions.update({"_id": x['_id']}, x)

    sessions = config.db.sessions.find({'files.size': {'$type': 'double'}})
    for x in sessions:
        for y in x.get('files', []):
            if y.get('size'):
                y['size'] = int(y['size'])
        config.db.sessions.update({"_id": x['_id']}, x)

    projects = config.db.projects.find({'files.size': {'$type': 'double'}})
    for x in projects:
        for y in x.get('files', []):
            if y.get('size'):
                y['size'] = int(y['size'])
        config.db.projects.update({"_id": x['_id']}, x)

    sessions = config.db.sessions.find({'analyses.files.size': {'$type': 'double'}})
    for x in sessions:
        for y in x.get('analyses', []):
            for z in y.get('files', []):
                if z.get('size'):
                    z['size'] = int(z['size'])
        config.db.sessions.update({"_id": x['_id']}, x)

def upgrade_to_17():
    """
    scitran/core issue #557

    Reassign subject ids after bug fix in packfile code that did not properly match subjects
    """

    pipeline = [
        {'$group' : { '_id' : {'pid': '$project', 'code': '$subject.code'}, 'sids': {'$push': '$_id' }}}
    ]

    subjects = config.db.command('aggregate', 'sessions', pipeline=pipeline)
    for subject in subjects['result']:

        # Subjects without a code and sessions without a subject
        # will be returned grouped together, but all need unique IDs
        if subject['_id'].get('code') is None:
            for session_id in subject['sids']:
                subject_id = bson.ObjectId()
                config.db.sessions.update_one({'_id': session_id},{'$set': {'subject._id': subject_id}})
        else:
            subject_id = bson.ObjectId()
            query = {'_id': {'$in': subject['sids']}}
            update = {'$set': {'subject._id': subject_id}}
            config.db.sessions.update_many(query, update)

def upgrade_to_18():
    """
    scitran/core issue #334

    Move singleton gear doc to its own table
    """

    gear_doc = config.db.singletons.find_one({"_id": "gears"})

    if gear_doc is not None:
        gear_list = gear_doc.get('gear_list', [])
        for gear in gear_list:
            try:
                gears.upsert_gear(gear)
            except Exception as e:
                logging.error("")
                logging.error("Error upgrading gear:")
                logging.error(type(e))
                logging.error("Gear will not be retained. Document follows:")
                logging.error(gear)
                logging.error("")

        config.db.singletons.remove({"_id": "gears"})

def upgrade_to_19():
    """
    scitran/core issue #552

    Add origin information to job object
    """

    update = {
        '$set': {
            'origin' : {'type': str(Origin.unknown), 'id': None}
        }
    }
    config.db.jobs.update_many({'origin': {'$exists': False}}, update)

def upgrade_to_20():
    """
    scitran/core issue #602

    Change dash to underscore for consistency
    """

    query = {'last-seen': {'$exists': True}}
    update = {'$rename': {'last-seen':'last_seen' }}

    config.db.devices.update_many(query, update)

def upgrade_to_21():
    """
    scitran/core issue #189 - Data Model v2

    Field `metadata` renamed to `info`
    Field `file.instrument` renamed to `file.modality`
    Acquisition fields `instrument` and `measurement` removed
    """

    def update_project_template(template):
        new_template = {'acquisitions': []}
        for a in template.get('acquisitions', []):
            new_a = {'minimum': a['minimum']}
            properties = a['schema']['properties']
            if 'measurement' in properties:
                m_req = properties['measurement']['pattern']
                m_req = re.sub('^\(\?i\)', '', m_req)
                new_a['files']=[{'measurement':  m_req, 'minimum': 1}]
            if 'label' in properties:
                l_req = properties['label']['pattern']
                l_req = re.sub('^\(\?i\)', '', l_req)
                new_a['label'] = l_req
            new_template['acquisitions'].append(new_a)

        return new_template

    def dm_v2_updates(cont_list, cont_name):
        for container in cont_list:

            query = {'_id': container['_id']}
            update = {'$rename': {'metadata': 'info'}}

            if cont_name == 'projects' and container.get('template'):
                new_template = update_project_template(json.loads(container.get('template')))
                update['$set'] = {'template': new_template}


            if cont_name == 'sessions':
                update['$rename'].update({'subject.metadata': 'subject.info'})


            measurement = None
            modality = None
            info = None
            if cont_name == 'acquisitions':
                update['$unset'] = {'instrument': '', 'measurement': ''}
                measurement = container.get('measurement', None)
                modality = container.get('instrument', None)
                info = container.get('metadata', None)
                if info:
                    config.db.acquisitions.update_one(query, {'$set': {'metadata': {}}})


            # From mongo docs: '$rename does not work if these fields are in array elements.'
            files = container.get('files')
            if files is not None:
                updated_files = []
                for file_ in files:
                    file_['info'] = {}
                    if 'metadata' in file_:
                        file_['info'] = file_.pop('metadata', None)
                    if 'instrument' in file_:
                        file_['modality'] = file_.pop('instrument', None)
                    if measurement:
                        # Move the acquisition's measurement to all files
                        if file_.get('measurements'):
                            file_['measurements'].append(measurement)
                        else:
                            file_['measurements'] = [measurement]
                    if info and file_.get('type', '') == 'dicom':
                        # This is going to be the dicom header info
                        updated_info = info
                        updated_info.update(file_['info'])
                        file_['info'] = updated_info
                    if modality and not file_.get('modality'):
                        file_['modality'] = modality

                    updated_files.append(file_)
                if update.get('$set'):
                    update['$set']['files'] =  updated_files
                else:
                    update['$set'] = {'files': updated_files}

            result = config.db[cont_name].update_one(query, update)

    query = {'$or':[{'files.metadata': { '$exists': True}},
                    {'metadata': { '$exists': True}},
                    {'files.instrument': { '$exists': True}}]}

    dm_v2_updates(config.db.collections.find(query), 'collections')

    query['$or'].append({'template': { '$exists': True}})
    dm_v2_updates(config.db.projects.find({}), 'projects')

    query['$or'].append({'subject': { '$exists': True}})
    dm_v2_updates(config.db.sessions.find(query), 'sessions')

    query['$or'].append({'instrument': { '$exists': True}})
    query['$or'].append({'measurement': { '$exists': True}})
    dm_v2_updates(config.db.acquisitions.find(query), 'acquisitions')

def upgrade_to_22():
    """
    Add created and modified timestamps to gear docs

    Of debatable value, since infra will load gears on each boot.
    """

    logging.info('Upgrade v22, phase 1 of 3, upgrading gears...')

    # Add timestamps to gears.
    for gear in config.db.gears.find({}):
        now = datetime.datetime.utcnow()

        gear['created']  = now
        gear['modified'] = now

        config.db.gears.update({'_id': gear['_id']}, gear)

        # Ensure there cannot possibly be two gears of the same name with the same timestamp.
        # Plus or minus monotonic time.
        # A very silly solution, but we only ever need to do this once, on a double-digit number of documents.
        # Not worth the effort to, eg, rewind time and do math.
        time.sleep(1)
        logging.info('  Updated gear ' + str(gear['_id']) + ' ...')
        sys.stdout.flush()


    logging.info('Upgrade v22, phase 2 of 3, upgrading jobs...')

    # Now that they're updated, fetch all gears and hold them in memory.
    # This prevents extra database queries during the job upgrade.

    all_gears = list(config.db.gears.find({}))
    gears_map = { }

    for gear in all_gears:
        gear_name = gear['gear']['name']

        gears_map[gear_name] = gear

    # A dummy gear for missing refs
    dummy_gear = {
        'category' : 'converter',
        'gear' : {
            'inputs' : {
                'do-not-use' : {
                    'base' : 'file'
                }
            },
            'maintainer' : 'Noone <nobody@example.example>',
            'description' : 'This gear or job was referenced before gear versioning. Version information is not available for this gear.',
            'license' : 'BSD-2-Clause',
            'author' : 'Noone',
            'url' : 'https://example.example',
            'label' : 'Deprecated Gear',
            'flywheel' : '0',
            'source' : 'https://example.example',
            'version' : '0.0.0',
            'custom' : {
                'flywheel': {
                    'invalid': True
                }
            },
            'config' : {},
            'name' : 'deprecated-gear'
        },
        'exchange' : {
            'git-commit' : '0000000000000000000000000000000000000000',
            'rootfs-hash' : 'sha384:000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
            'rootfs-url' : 'https://example.example/does-not-exist.tgz'
        }
    }

    maximum = config.db.jobs.count()
    upgraded = 0

    # Blanket-assume gears were the latest in the DB pre-gear versioning.
    for job in config.db.jobs.find({}):

        # Look up latest gear by name, lose job name key
        gear_name = job['name']
        gear = gears_map.get(gear_name)

        if gear is None:
            logging.info('Job doc ' + str(job['_id']) + ' could not find gear ' + gear_name + ', creating...')

            new_gear = copy.deepcopy(dummy_gear)
            new_gear['gear']['name'] = gear_name

            # Save new gear, store id in memory
            resp = config.db.gears.insert_one(new_gear)
            new_id = resp.inserted_id
            new_gear['_id'] = str(new_id)

            # Insert gear into memory map
            gears_map[gear_name] = new_gear

            logging.info('Created gear  ' + gear_name + ' with id ' + str(new_id) + '. Future jobs with this gear name with not alert.')

            gear = new_gear

        if gear is None:
            raise Exception("We don't understand python scopes ;( ;(")

        # Store gear ID
        job.pop('name', None)
        job['gear_id'] = str(gear['_id'])

        # Save
        config.db.jobs.update({'_id': job['_id']}, job)

        upgraded += 1
        if upgraded % 1000 == 0:
            logging.info('  Processed ' + str(upgraded) + ' jobs of ' + str(maximum) + '...')


    logging.info('Upgrade v22, phase 3 of 3, upgrading batch...')

    maximum = config.db.batch.count()
    upgraded = 0

    for batch in config.db.batch.find({}):

        # Look up latest gear by name, lose job name key
        gear = gears.get_gear_by_name(batch['gear'])
        batch.pop('gear', None)

        # Store gear ID
        batch['gear_id'] = str(gear['_id'])

        # Save
        config.db.batch.update({'_id': batch['_id']}, batch)

        upgraded += 1
        if upgraded % 1000 == 0:
            logging.info('  Processed ' + str(upgraded) + ' batch of ' + str(maximum) + '...')


    logging.info('Upgrade v22, complete.')

def upgrade_to_23():
    """
    scitran/core issue #650

    Support multiple auth providers
    Config 'auth' key becomes map where keys are auth_type
    """

    db_config = config.db.singletons.find_one({'_id': 'config'})
    if db_config:
        auth_config = db_config.get('auth', {})
        if auth_config.get('auth_type'):
            auth_type = auth_config.pop('auth_type')
            config.db.singletons.update_one({'_id': 'config'}, {'$set': {'auth': {auth_type: auth_config}}})

def upgrade_to_24():
    """
    scitran/core issue #720

    Migrate gear rules to the project level
    """

    global_rules = config.db.singletons.find_one({"_id" : "rules"})
    project_ids  = list(config.db.projects.find({},{"_id": "true"}))

    if global_rules is None:
        global_rules = {
            'rule_list': []
        }

    logging.info('Upgrade v23, migrating ' + str(len(global_rules['rule_list'])) + ' gear rules...')

    count = 0
    for old_rule in global_rules['rule_list']:

        logging.info(json.dumps(old_rule))

        gear_name = old_rule['alg']
        rule_name = 'Migrated rule ' + str(count)

        any_stanzas = []
        all_stanzas = []

        for old_any_stanza in old_rule.get('any', []):
            if len(old_any_stanza) != 2:
                raise Exception('Confusing any-rule stanza ' + str(count) + ': ' + json.dumps(old_any_stanza))

            any_stanzas.append({ 'type': old_any_stanza[0], 'value': old_any_stanza[1] })

        for old_all_stanza in old_rule.get('all', []):
            if len(old_all_stanza) != 2:
                raise Exception('Confusing all-rule stanza ' + str(count) + ': ' + json.dumps(old_all_stanza))

            all_stanzas.append({ 'type': old_all_stanza[0], 'value': old_all_stanza[1] })

        # New rule object
        new_rule = {
            'alg': gear_name,
            'name': rule_name,
            'any': any_stanzas,
            'all': all_stanzas
        }

        # Insert rule on every project
        for project in project_ids:
            project_id = project['_id']

            new_rule_obj = copy.deepcopy(new_rule)
            new_rule_obj['project_id'] = str(project_id)

            config.db.project_rules.insert_one(new_rule_obj)

        logging.info('Upgrade v23, migrated rule ' + str(count) + ' of ' + str(len(global_rules)) + '...')
        count += 1

    # Remove obsolete singleton
    config.db.singletons.remove({"_id" : "rules"})
    logging.info('Upgrade v23, complete.')

def upgrade_to_25():
    """
    scitran/core PR #733

    Migrate refresh token from authtokens to seperate collection
    """

    auth_tokens = config.db.authtokens.find({'refresh_token': {'$exists': True}})

    for a in auth_tokens:
        refresh_doc = {
            'uid': a['uid'],
            'token': a['refresh_token'],
            'auth_type': a['auth_type']
        }
        config.db.refreshtokens.insert(refresh_doc)

    config.db.authtokens.update_many({'refresh_token': {'$exists': True}}, {'$unset': {'refresh_token': ''}})

def upgrade_to_26_closure(job):

    gear = config.db.gears.find_one({'_id': bson.ObjectId(job['gear_id'])}, {'gear.name': 1})

    # This logic WILL NOT WORK in parallel mode
    if gear is None:
        logging.info('No gear found for job ' + str(job['_id']))
        return True
    if gear.get('gear', {}).get('name', None) is None:
        logging.info('No gear found for job ' + str(job['_id']))
        return True

    # This logic WILL NOT WORK in parallel mode

    gear_name = gear['gear']['name']

    # Checks if the specific gear tag already exists for the job
    if gear_name in job['tags']:
        return True

    result = config.db.jobs.update_one({'_id': job['_id']}, {'$addToSet': {'tags': gear_name }})

    if result.modified_count == 1:
        return True
    else:
        return 'Parallel failed: update doc ' + str(job['_id']) + ' resulted modified ' + str(result.modified_count)


def upgrade_to_26():
    """
    scitran/core #734

    Add job tags back to the job document, and use a faster cursor-walking update method
    """
    cursor = config.db.jobs.find({})
    process_cursor(cursor, upgrade_to_26_closure)


def upgrade_to_27():
    """
    scitran/core PR #768

    Fix project templates that reference `measurement` instead of `measurements`
    Update all session compliance for affected projects
    """

    projects = config.db.projects.find({'template.acquisitions.files.measurement': {'$exists': True}})

    storage = ProjectStorage()

    for p in projects:
        template = p.get('template', {})
        for a in template.get('acquisitions', []):
            for f in a.get('files', []):
                if f.get('measurement'):
                    f['measurements'] = f.pop('measurement')
        config.log.debug('the template is now {}'.format(template))
        config.db.projects.update_one({'_id': p['_id']}, {'$set': {'template': template}})
        storage.recalc_sessions_compliance(project_id=str(p['_id']))

def upgrade_to_28():
    """
    Fixes session.subject.age sometimes being a floating-point rather than integer.
    """

    sessions = config.db.sessions.find({'subject.age': {'$type': 'double'}})
    logging.info('Fixing {} subjects with age stored as double ...'.format(sessions.count()))
    for session in sessions:
        try:
            session['subject']['age'] = int(session['subject']['age'])
        except:
            session['subject']['age'] = None

        config.db.sessions.update({'_id': session['_id']}, session)




def upgrade_to_29_closure(user):

    avatars = user['avatars']
    if avatars.get('custom') and not 'https:' in avatars['custom']:
        if user['avatar'] == user['avatars']['custom']:
            if(user['avatars'].get('provider') == None):
                config.db.users.update_one({'_id': user['_id']},
                    {'$unset': {'avatar': ""}})
            else:
                config.db.users.update_one({'_id': user['_id']},
                    {'$set': {'avatar': user['avatars'].get('provider')}}
                )
        logging.info('Deleting custom ...')
        config.db.users.update_one({'_id': user['_id']},
            {'$unset': {"avatars.custom": ""}}
        )
    return True


def upgrade_to_29():
    """
    Enforces HTTPS urls for user avatars
    """

    users = config.db.users.find({})
    process_cursor(users, upgrade_to_29_closure)

def upgrade_to_30_closure_analysis(coll_item, coll):
    analyses = coll_item.get('analyses', [])

    for analysis_ in analyses:
        files = analysis_.get('files', [])
        for file_ in files:
            if 'created' not in file_:
                file_['created'] = analysis_.get('created', datetime.datetime(1970, 1, 1))
    result = config.db[coll].update_one({'_id': coll_item['_id']}, {'$set': {'analyses': analyses}})
    if result.modified_count == 1:
        return True
    else:
        return "File timestamp creation failed for:" + str(coll_item)

def upgrade_to_30_closure_coll(coll_item, coll):
    files = coll_item.get('files', [])
    for file_ in files:
        if 'created' not in file_:
            file_['created'] = coll_item.get('created', datetime.datetime(1970, 1, 1))
    result = config.db[coll].update_one({'_id': coll_item['_id']}, {'$set': {'files': files}})
    if result.modified_count == 1:
        return True
    else:
        return "File timestamp creation failed for:" + str(coll_item)


def upgrade_to_30():
    """
    scitran/core issue #759

    give created timestamps that are missing are given based on the parent object's timestamp
    """

    cursor = config.db.collections.find({'analyses.files.name': {'$exists': True},
                                         'analyses.files.created': {'$exists': False}})
    process_cursor(cursor, upgrade_to_30_closure_analysis, context = 'collections')

    cursor = config.db.sessions.find({'analyses.files.name': {'$exists': True},
                                      'analyses.files.created': {'$exists': False}})
    process_cursor(cursor, upgrade_to_30_closure_analysis, context = 'sessions')

    cursor = config.db.sessions.find({'files.name': {'$exists': True}, 'files.created': {'$exists': False}})
    process_cursor(cursor, upgrade_to_30_closure_coll, context = 'sessions')

    cursor = config.db.collections.find({'files.name': {'$exists': True}, 'files.created': {'$exists': False}})
    process_cursor(cursor, upgrade_to_30_closure_coll, context = 'collections')

    cursor = config.db.acquisitions.find({'files.name': {'$exists': True}, 'files.created': {'$exists': False}})
    process_cursor(cursor, upgrade_to_30_closure_coll, context = 'acquisitions')

    cursor = config.db.projects.find({'files.name': {'$exists': True}, 'files.created': {'$exists': False}})
    process_cursor(cursor, upgrade_to_30_closure_coll, context = 'projects')

def upgrade_to_31():
    config.db.sessions.update_many({'subject.firstname_hash': {'$exists': True}}, {'$unset': {'subject.firstname_hash':""}})
    config.db.sessions.update_many({'subject.lastname_hash': {'$exists': True}}, {'$unset': {'subject.lastname_hash':""}})

def upgrade_to_32_closure(coll_item, coll):
    permissions = coll_item.get('permissions', [])
    for permission_ in permissions:
        if permission_.get('site', False):
            del permission_['site']
    result = config.db[coll].update_one({'_id': coll_item['_id']}, {'$set': {'permissions' : permissions}})
    if result.modified_count == 0:
        return "Failed to remove site field"
    return True

def upgrade_to_32():
    for coll in ['acquisitions', 'groups', 'projects', 'sessions']:
        cursor = config.db[coll].find({'permissions.site': {'$exists': True}})
        process_cursor(cursor, upgrade_to_32_closure, context = coll)
    config.db.sites.drop()

def upgrade_to_33_closure(cont, cont_name):
    cont_type = cont_name[:-1]
    if cont.get('analyses'):
        for analysis in cont['analyses']:
            analysis['_id'] = bson.ObjectId(analysis['_id'])
            analysis['parent'] = {'type': cont_type, 'id': cont['_id']}
            analysis['permissions'] = cont['permissions']
            for key in ('public', 'archived'):
                if key in cont:
                    analysis[key] = cont[key]
        config.db['analyses'].insert_many(cont['analyses'])
    config.db[cont_name].update_one(
        {'_id': cont['_id']},
        {'$unset': {'analyses': ''}})
    return True

def upgrade_to_33():
    """
    scitran/core issue #808 - make analyses use their own collection
    """
    for cont_name in ['projects', 'sessions', 'acquisitions', 'collections']:
        cursor = config.db[cont_name].find({'analyses': {'$exists': True}})
        process_cursor(cursor, upgrade_to_33_closure, context=cont_name)

def upgrade_to_34():
    """
    Changes group.roles -> groups.permissions

    scitran/core #662
    """
    config.db.groups.update_many({'roles': {'$exists': True}}, {'$rename': {'roles': 'permissions'}})
    config.db.groups.update_many({'name': {'$exists': True}}, {'$rename': {'name': 'label'}})

def upgrade_to_35_closure(batch_job):
    if batch_job.get('state') in ['cancelled', 'running', 'complete', 'failed']:
        return True
    batch_id = batch_job.get('_id')
    config.db.jobs.update_many({'_id': {'$in': batch_job.get('jobs',[])}}, {'$set': {'batch':batch_id}})
    new_state = batch.check_state(batch_id)
    if new_state:
        result = config.db.batch.update_one({'_id': batch_id}, {'$set': {"state": new_state}})
        if result.modified_count != 1:
            raise Exception('Batch job not updated')
    else:
        result = config.db.batch.update_one({'_id': batch_id}, {'$set': {"state": "running"}})
        if result.modified_count != 1:
            raise Exception('Batch job not updated')
    return True

def upgrade_to_35():
    """
    scitran/core issue #710 - give batch stable states
    """
    cursor = config.db.batch.find({})
    process_cursor(cursor, upgrade_to_35_closure)


def upgrade_to_36_closure(acquisition):

    for f in acquisition['files']:
        if not f.get('mimetype'):
            logging.debug('file with name {} did not have mimetype'.format(f['name']))
            f['mimetype'] = util.guess_mimetype(f['name'])

    result = config.db.acquisitions.update_one({'_id': acquisition['_id']}, {'$set': {'files': acquisition['files']}})
    if result.modified_count != 1:
        raise Exception('Acquisition file not updated')

    return True


def upgrade_to_36():
    """
    scitran/core issue #931 - mimetype not set on packfile uploads
    """
    cursor = config.db.acquisitions.find({'files': { '$gt': [] }, 'files.mimetype': None})
    process_cursor(cursor, upgrade_to_36_closure)

def upgrade_to_37():
    """
    scitran/core issue #916 - group-permission level site info needs to be removed from all levels
    """
    for coll in ['acquisitions', 'groups', 'projects', 'sessions', 'analyses']:
        cursor = config.db[coll].find({'permissions.site': {'$exists': True}})
        process_cursor(cursor, upgrade_to_32_closure, context = coll)


def upgrade_to_38_closure(user):

    # if user has existing API key in correct db location, remove API key stored on user and move on
    # otherwise, migrate api key to new location

    api_key = user['api_key']
    doc = config.db.apikeys.find_one({'uid': user['_id'], 'type': 'user'})

    if not doc:

        # migrate existing API key

        new_api_key_doc = {
            '_id': api_key['key'],
            'created': api_key['created'],
            'last_used': api_key['last_used'],
            'uid': user['_id'],
            'type': 'user'
        }

        config.db.apikeys.insert(new_api_key_doc)

    config.db.users.update_one({'_id': user['_id']}, {'$unset': {'api_key': 0}})

    return True


def upgrade_to_38():
    """
    Move existing user api keys to new 'apikeys' collection
    """
    cursor = config.db.users.find({'api_key': {'$exists': True }})
    process_cursor(cursor, upgrade_to_38_closure)


def upgrade_to_39_closure(job):
    """
    Done in python because:
    " the source and target field for $rename must not be on the same path "
    """

    config_ = job.pop('config', {})
    config.db.jobs.update({'_id': job['_id']}, {'$set': {'config': {'config': config_}}})

    return True

def upgrade_to_39():
    """
    Move old jobs without extra config down one level to match new jobs
    with additional keys.

    Before:
    {
        'config': {
            'a': 'b'
        }
    }

    After:
    {
        'config': {
            'config': {
                'a': 'b'
            }
        }
    }
    """
    cursor = config.db.jobs.find({'config': {'$exists': True }, 'config.config': {'$exists': False }})
    process_cursor(cursor, upgrade_to_39_closure)


def upgrade_to_40_closure(acquisition):
    config.db.acquisitions.update_one({'_id':acquisition['_id']},{'$set':{'timestamp':dateutil.parser.parse(acquisition['timestamp'])}})
    return True

def upgrade_to_40():
    """
    Convert all string acquisition timestamps to type date
    """
    cursor = config.db.acquisitions.find({'timestamp':{'$type':'string'}})
    process_cursor(cursor, upgrade_to_40_closure)


def upgrade_to_41_closure(cont, cont_name):

    files = cont.get('files', [])
    for f in files:
        if 'tags' not in f:
            f['tags'] = []
        if 'measurements' not in f:
            f['measurements'] = []
        if 'origin' not in f:
            f['origin'] = {
                'type': str(Origin.unknown),
                'id': None
            }
        if 'mimetype' not in f:
            f['mimetype'] = util.guess_mimetype(f.get('name'))
        if 'modality' not in f:
            f['modality'] = None
    config.db[cont_name].update_one({'_id': cont['_id']}, {'$set': {'files': files}})
    return True


def upgrade_to_41():
    """
    scitran/core issue #1042 - some "expected" file default keys are not present

    These are the fields that are created on every file object in upload.py
    """

    for cont_name in ['groups', 'projects', 'sessions', 'acquisitions', 'collections', 'analyses']:
        cursor = config.db[cont_name].find({'files': { '$elemMatch': { '$or': [
            {'tags':          {'$exists': False }},
            {'measurements':  {'$exists': False }},
            {'origin':        {'$exists': False }},
            {'mimetype':      {'$exists': False }},
            {'modality':      {'$exists': False }}
        ]}}})
        process_cursor(cursor, upgrade_to_41_closure, context=cont_name)


def upgrade_to_42_closure(cont, cont_name):
    archived = cont.pop('archived')
    update = {'$unset': {'archived': True}}
    if archived:
        cont['tags'] = cont.get('tags', []) + ['hidden']
        update['$set'] = {'tags': cont['tags']}
    config.db[cont_name].update_one({'_id': cont['_id']}, update)
    return True

def upgrade_to_42():
    """
    Change container flag "archived" to container tag "hidden"
    """
    for cont_name in ['groups', 'projects', 'sessions', 'acquisitions']:
        cursor = config.db[cont_name].find({'archived': {'$exists': True}})
        process_cursor(cursor, upgrade_to_42_closure, context=cont_name)


def upgrade_to_43_closure(cont, cont_name):
    """
    Update all files in a collection that do not have a version
    """
    files = cont.get('files', [])
    for f in files:
        if 'version' not in f:
            f['version'] = 1
    config.db[cont_name].update_one({'_id': cont['_id']}, {'$set': {'files': files}})
    return True


def upgrade_to_43():
    """
    Add initial file versioning to all files
    """
    for cont_name in ['projects', 'sessions', 'acquisitions', 'analyses', 'collections']:
        cursor = config.db[cont_name].find({'files': { '$gt': [] }, 'files.version': {'$exists': False }})
        process_cursor(cursor, upgrade_to_43_closure, context=cont_name)


###
### BEGIN RESERVED UPGRADE SECTION
###

# Due to performance concerns with database upgrades, some upgrade implementations might be postposed.
# The team contract is that if you write an upgrade touch one of the tables mentioned below, you MUST also implement any reserved upgrades.
# This way, we can bundle changes together that need large cursor iterations and save multi-hour upgrade times.



###
### END RESERVED UPGRADE SECTION
###


def upgrade_schema(force_from = None):
    """
    Upgrades db to the current schema version

    Returns (0) if upgrade is successful
    """

    db_version = get_db_version()

    if force_from:
        if isinstance(db_version,int) and db_version >= force_from:
            db_version = force_from
        else:
            logging.error('Cannot force from future version %s. Database only at version %s', str(force_from), str(db_version))
            sys.exit(43)


    if not isinstance(db_version, int) or db_version > CURRENT_DATABASE_VERSION:
        logging.error('The stored db schema version of %s is incompatible with required version %s',
                       str(db_version), CURRENT_DATABASE_VERSION)
        sys.exit(43)
    elif db_version == CURRENT_DATABASE_VERSION:
        logging.error('Database already up to date.')
        sys.exit(43)

    try:
        while db_version < CURRENT_DATABASE_VERSION:
            db_version += 1
            upgrade_script = 'upgrade_to_'+str(db_version)
            logging.info('Upgrading to version {} ...'.format(db_version))
            globals()[upgrade_script]()
            logging.info('Upgrade to version {} complete.'.format(db_version))
    except KeyError as e:
        logging.exception('Attempted to upgrade using script that does not exist: {}'.format(e))
        sys.exit(1)
    except Exception as e:
        logging.exception('Incremental upgrade of db failed')
        sys.exit(1)
    else:
        config.db.singletons.update_one({'_id': 'version'}, {'$set': {'database': CURRENT_DATABASE_VERSION}})
        sys.exit(0)

if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("function", help="function to be called from database.py")
        parser.add_argument("-f", "--force_from", help="force database to upgrade from previous version", type=int)
        args = parser.parse_args()

        if args.function == 'confirm_schema_match':
            confirm_schema_match()
        elif args.function == 'upgrade_schema':
            if args.force_from:
                upgrade_schema(args.force_from)
            else:
                upgrade_schema()
        else:
            logging.error('Unknown method name given as argv to database.py')
            sys.exit(1)
    except Exception as e:
        logging.exception('Unexpected error in database.py')
        sys.exit(1)
