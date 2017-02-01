#!/usr/bin/env python

import bson
import copy
import dateutil.parser
import json
import logging
import re
import sys

from api import config
from api.dao import containerutil
from api.jobs.jobs import Job
from api.jobs import gears
from api.types import Origin

CURRENT_DATABASE_VERSION = 22 # An int that is bumped when a new schema change is made

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
    Change file `measurement` field to `classification` map
    Place all measurements in `custom` key on map
    """

    def update_project_template(template):
        for a in template.get('acquisitions', []):
            new_file_templates = []
            for f in a.get('files', []):
                if f.get('measurement'):
                    measurements = f.pop('measurement')
                    f['classification'] = {'custom': measurement}

        return template


    def change_to_classification(cont_list, cont_name):
        for container in cont_list:

            if cont_name == 'projects' and container.get('template'):
                new_template = update_project_template(json.loads(container.get('template')))
                update['$set'] = {'template': new_template}

            query = {'_id': container['_id']}
            update = {}

            files = container.get('files')
            if files is not None:
                updated_files = []
                for file_ in files:
                    if 'measurements' in file_:
                        measurements = file_.pop('measurements', [])
                        custom = {'custom': measurements}
                        file_['classification'] = custom

                    updated_files.append(file_)
                if update.get('$set'):
                    update['$set']['files'] =  updated_files
                else:
                    update['$set'] = {'files': updated_files}

            result = config.db[cont_name].update_one(query, update)

    query = {'files.measurements': { '$exists': True}}

    change_to_classification(config.db.collections.find(query), 'collections')
    change_to_classification(config.db.projects.find(query), 'projects')
    change_to_classification(config.db.sessions.find(query), 'sessions')
    change_to_classification(config.db.acquisitions.find(query), 'acquisitions')


def upgrade_schema():
    """
    Upgrades db to the current schema version

    Returns (0) if upgrade is successful
    """

    db_version = get_db_version()
    try:
        while db_version < CURRENT_DATABASE_VERSION:
            db_version += 1
            upgrade_script = 'upgrade_to_'+str(db_version)
            globals()[upgrade_script]()
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
        if len(sys.argv) > 1:
            if sys.argv[1] == 'confirm_schema_match':
                confirm_schema_match()
            elif sys.argv[1] == 'upgrade_schema':
                upgrade_schema()
            else:
                logging.error('Unknown method name given as argv to database.py')
                sys.exit(1)
        else:
            logging.error('No method name given as argv to database.py')
            sys.exit(1)
    except Exception as e:
        logging.exception('Unexpected error in database.py')
        sys.exit(1)
