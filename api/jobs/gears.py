"""
Gears
"""

from __future__ import absolute_import

import bson.objectid
import datetime
from jsonschema import Draft4Validator, ValidationError
import gears as gear_tools
import pymongo

from .. import config
from .jobs import Job
from ..dao import APIValidationException
from ..dao.base import ContainerStorage

log = config.log

def get_gears():
    """
    Fetch the install-global gears from the database
    """

    pipe = [
        {'$sort': {
            'gear.name': 1,
            'created': -1,
        }},
        {'$group': {
            '_id': { 'name': '$gear.name' },
            'original': { '$first': '$$CURRENT' }
        }}
    ]

    cursor = config.mongo_pipeline('gears', pipe)

    return map(lambda x: x['original'], cursor)

def get_gear(_id):
    return config.db.gears.find_one({'_id': bson.ObjectId(_id)})

def get_gear_by_name(name):

    # Find a gear from the list by name
    gear_doc = list(config.db.gears.find({'gear.name': name}).sort('created', pymongo.DESCENDING))

    if len(gear_doc) == 0 :
        raise Exception('Unknown gear ' + name)

    return gear_doc[0]

def get_invocation_schema(gear):
    return gear_tools.derive_invocation_schema(gear['gear'])

def suggest_container(gear, cont_name, cid):
    """
    Given a container reference, suggest files that would work well for each input on a gear.
    """

    root = ContainerStorage.factory(cont_name).get_container(cid, projection={'permissions':0}, get_children=True)
    invocation_schema = get_invocation_schema(gear)

    schemas = {}
    for x in gear['gear']['inputs']:
        schema = gear_tools.isolate_file_invocation(invocation_schema, x)
        schemas[x] = Draft4Validator(schema)

    # It would be nice to have use a visitor here instead of manual key loops.
    for acq in root.get('acquisitions', []):
        for f in acq.get('files', []):
            f['suggested'] = {}
            for x in schemas:
                f['suggested'][x] = schemas[x].is_valid(f)

    for analysis in root.get('analyses',{}): # cover 100
        files = analysis.get('files', [])
        files[:] = [x for x in files if x.get('output')]
        for f in files:
            f['suggested'] = {}
            for x in schemas:
                f['suggested'][x] = schemas[x].is_valid(f)
        analysis['files'] = files

    return root

def suggest_for_files(gear, files):

    invocation_schema = get_invocation_schema(gear)
    schemas = {}
    for x in gear['gear']['inputs']:
        schema = gear_tools.isolate_file_invocation(invocation_schema, x)
        schemas[x] = Draft4Validator(schema)

    suggested_files = {}
    log.debug(schemas)
    for input_name, schema in schemas.iteritems():
        suggested_files[input_name] = []
        for f in files:
            if schema.is_valid(f):
                suggested_files[input_name].append(f.get('name'))

    return suggested_files

def validate_gear_config(gear, config_):
    if len(gear.get('manifest', {}).get('config', {})) > 0: # cover 100
        invocation = gear_tools.derive_invocation_schema(gear['manifest'])
        ci = gear_tools.isolate_config_invocation(invocation)
        validator = Draft4Validator(ci)

        try:
            validator.validate(config_)
        except ValidationError as err:
            key = None
            if len(err.relative_path) > 0:
                key = err.relative_path[0]

            raise APIValidationException({
                'reason': 'config did not match manifest',
                'error': err.message.replace("u'", "'"),
                'key': key
            })
    return True

def insert_gear(doc):
    gear_tools.validate_manifest(doc['gear'])

    # This can be mongo-escaped and re-used later
    if doc.get("invocation-schema"): # cover 100
        del(doc["invocation-schema"])

    now = datetime.datetime.utcnow()

    doc['created']  = now
    doc['modified'] = now

    result = config.db.gears.insert(doc)

    if config.get_item('queue', 'prefetch'): # cover 100
        log.info('Queuing prefetch job for gear ' + doc['gear']['name'])

        job = Job(str(doc['_id']), {}, destination={}, tags=['prefetch'], request={
            'inputs': [
                {
                    'type': 'http',
                    'uri': doc['exchange']['rootfs-url'],
                    'vu': 'vu0:x-' + doc['exchange']['rootfs-hash']
                }
            ],
            'target': {
                'command': ['uname', '-a'],
                'env': {
                    'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                },
            },
            'outputs': [ ],
        })
        job.insert()

    return result


def remove_gear(_id):
    result = config.db.gears.delete_one({"_id": bson.ObjectId(_id)})

    if result.deleted_count != 1: # cover 100
        raise Exception("Deleted failed " + str(result.raw_result))

def upsert_gear(doc):
    gear_tools.validate_manifest(doc['gear'])

    # Remove previous gear if name & version combo already exists

    conflict = config.db.gears.find_one({
        'gear.name': doc['gear']['name'],
        'gear.version': doc['gear']['version']
    })

    if conflict is not None:
        raise Exception('Gear ' + doc['gear']['name'] + ' ' + doc['gear']['version'] + ' already exists')

    return insert_gear(doc)
