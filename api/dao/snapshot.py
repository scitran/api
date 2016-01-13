from .. import config
import bson.objectid
from pymongo import ReturnDocument


def _new_version(project_id):
    project_id = bson.objectid.ObjectId(project_id)
    project = config.db.projects.find_one_and_update(
        {'_id': project_id},
        {'$inc': {'snapshot_version': 1}},
        return_document=ReturnDocument.AFTER
    )
    version = {
        'snapshot': project
    }
    sessions = list(config.db.sessions.find({'project': project_id}, {'project': 0, 'permissions': 0}))
    for session in sessions:
        acquisitions = list(config.db.acquisitions.find({'session': session['_id']}, {'session': 0, 'permissions': 0}))
        session['permissions'] = project['permissions']
        for a in acquisitions:
            a['permissions'] = project['permissions']
        version[session['_id']] = acquisitions
    version[project_id] = sessions
    return version


def _store(hierarchy):
    project = hierarchy['snapshot']
    project['original'] = project.pop('_id')
    result = config.db.project_snapshots.insert_one(project)
    project_id = result.inserted_id
    for session in hierarchy[project['original']]:
        session['project'] = project_id
        session['original'] = session.pop('_id')
    sessions = config.db.session_snapshots.insert_many(hierarchy[project['original']])
    session_ids = sessions.inserted_ids
    acquisitions = []
    for i, session in enumerate(hierarchy[project['original']]):
        session_id = session_ids[i]
        for acquisition in hierarchy[session['original']]:
            acquisition['session'] = session_id
            acquisition['original'] = acquisition.pop('_id')
            acquisitions.append(acquisition)
        hierarchy[session_id] = hierarchy.pop(session['original'])
    hierarchy[project_id] = hierarchy.pop(project['original'])
    config.db.acquisition_snapshots.insert_many(acquisitions)
    return result


def create(method, _id):
    hierarchy = _new_version(_id)
    return _store(hierarchy)


def remove(method, _id):
    snapshot_id = bson.objectid.ObjectId(_id)
    result = config.db.project_snapshots.find_one_and_delete({'_id': snapshot_id})
    session_snapshot_ids = [s['_id'] for s in config.db.session_snapshots.find({'project': snapshot_id})]
    config.db.session_snapshots.delete_many({'_id': {'$in': session_snapshot_ids}})
    config.db.acquisition_snapshots.delete_many({'session': {'$in': session_snapshot_ids}})
    return result


def make_public(method, _id, public=True):
    snapshot_id = bson.objectid.ObjectId(_id)
    result = config.db.project_snapshots.find_one_and_update({'_id': snapshot_id}, {'$set':{'public': public}})
    session_snapshot_ids = [s['_id'] for s in config.db.session_snapshots.find({'project': snapshot_id})]
    config.db.session_snapshots.update_many({'_id': {'$in': session_snapshot_ids}}, {'$set':{'public': public}})
    config.db.acquisition_snapshots.update_many({'session': {'$in': session_snapshot_ids}}, {'$set':{'public': public}})
    return result
