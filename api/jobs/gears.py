"""
Gears
"""

from .. import config
from ..request import get_current_request
from .jobs import Job

# For now, gears are in a singleton, prefixed by a key
SINGLETON_KEY = 'gear_list'

def get_gears(fields=None):
    """
    Fetch the install-global gears from the database
    """

    projection = { }

    if fields is None:
        fields = [ ]
        projection = { SINGLETON_KEY: 1 }
    else:
        fields.append('name')

    query = {'_id': 'gears'}

    for f in fields:
        projection[SINGLETON_KEY + '.' + f] = 1

    gear_doc = config.db.singletons.find_one(query, projection)

    # print gear_doc
    return gear_doc[SINGLETON_KEY]

def get_gear_by_name(name):

    # Find a gear from the list by name
    gear_doc = config.db.singletons.find_one(
        {'_id': 'gears'},
        {SINGLETON_KEY: { '$elemMatch': {
            'name': name
        }}
    })

    if gear_doc is None or gear_doc.get(SINGLETON_KEY) is None:
        raise Exception('Unknown gear ' + name)

    # Mongo returns the full document: { '_id' : 'gears', 'gear_list' : [ { .. } ] }, so strip that out
    return gear_doc[SINGLETON_KEY][0]

def insert_gear(doc):
    config.db.singletons.update(
        {"_id" : "gears"},
        {'$push': {'gear_list': doc} }
    )

    if config.get_item('queue', 'prefetch'):
        request = get_current_request()
        request.logger.info('Queuing prefetch job for gear ' + doc['name'])

        job = Job(doc['name'], {}, destination={}, tags=['prefetch'], request={
            'inputs': [
                doc['input']
            ],
            'target': {
                'command': ['uname', '-a'],
                'env': {
                    'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
                },
            },
            'outputs': [ ],
        })
        return job.insert()

def remove_gear(name):
    config.db.singletons.update(
        {"_id" : "gears"},
        {'$pull': {'gear_list':{ 'name': name }} }
    )

def upsert_gear(doc):
    remove_gear(doc['name'])
    insert_gear(doc)
