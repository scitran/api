import bson.errors
import bson.objectid

from .. import util
from .. import config
from . import APIStorageException

log = config.log

def project_purge(method, _id, payload=None):
    assert method == 'DELETE'
    sessions = config.db.sessions.find({'project': bson.objectid.ObjectId(_id)})
    session_ids = [s['_id'] for s in sessions]

    delete_acquisitions = config.db.acquisitions.delete_many({'session': {'$in': session_ids}})
    if not delete_acquisitions.acknowledged:
        raise APIStorageException('acquisitions within sessions {} have not been deleted'.format(session_ids))

    delete_sessions = config.db.sessions.delete_many({'project': bson.objectid.ObjectId(_id)})
    if not delete_sessions.acknowledged:
        raise APIStorageException('sessions within project {} have not been deleted'.format(_id))

def acquisitions_in_project(method, _id, payload=None):
    assert method == 'GET'
    sessions = config.db.sessions.find({'project': bson.objectid.ObjectId(_id)})
    ids = [s['_id'] for s in sessions]
    return list(config.db.acquisitions.find({'session': {'$in': ids}}))

def acquisitions_in_project_snapshot(method, _id, payload=None):
    assert method == 'GET'
    sessions = config.db.session_snapshots.find({'project': bson.objectid.ObjectId(_id)})
    ids = [s['_id'] for s in sessions]
    return list(config.db.acquisition_snapshots.find({'session': {'$in': ids}}))
