import bson
import copy
import datetime
import dateutil.parser
import difflib
import pymongo
import re

from .. import files
from .. import util
from .. import config
from .basecontainerstorage import ContainerStorage
from ..auth import has_access
from ..web.errors import APIStorageException, APINotFoundException, APIPermissionException
from . import containerutil

log = config.log

PROJECTION_FIELDS = ['group', 'name', 'label', 'timestamp', 'permissions', 'public']

class TargetContainer(object):

    def __init__(self, container, level):
        if level == 'subject':
            self.container = container.get('subject')
            self.level = level
            self.dbc = config.db['sessions']
            self.id_ = container['_id']
            self.file_prefix = 'subject.files'
        else:
            self.container = container
            self.level = level
            self.dbc = config.db[level]
            self.id_ = container['_id']
            self.file_prefix = 'files'

    def find(self, filename):
        for f in self.container.get('files', []):
            if f['name'] == filename:
                return f
        return None

    def upsert_file(self, fileinfo):
        result = self.dbc.find_one({'_id': self.id_, self.file_prefix + '.name': fileinfo['name']})
        if result:
            self.update_file(fileinfo)
        else:
            self.add_file(fileinfo)

    def update_file(self, fileinfo):
        update_set = {self.file_prefix + '.$.modified': datetime.datetime.utcnow()}
        # in this method, we are overriding an existing file.
        # update_set allows to update all the fileinfo like size, hash, etc.
        for k,v in fileinfo.iteritems():
            update_set[self.file_prefix + '.$.' + k] = v
        return self.dbc.find_one_and_update(
            {'_id': self.id_, self.file_prefix + '.name': fileinfo['name']},
            {'$set': update_set},
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

    def add_file(self, fileinfo):
        return self.dbc.find_one_and_update(
            {'_id': self.id_},
            {'$push': {self.file_prefix: fileinfo}},
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

# TODO: already in code elsewhere? Location?
def get_container(cont_name, _id):
    cont_name = containerutil.pluralize(cont_name)
    if cont_name != 'groups':
        _id = bson.ObjectId(_id)

    return config.db[cont_name].find_one({
        '_id': _id,
    })

def get_parent_tree(cont_name, _id):
    """
    Given a contanier and an id, returns that container and its parent tree.

    For example, given `sessions`, `<session_id>`, it will return:
    {
        'session':  <session>,
        'project':  <project>,
        'group':    <group>
    }
    """
    cont_name = containerutil.singularize(cont_name)


    if cont_name not in ['acquisition', 'session', 'project', 'group', 'analysis']:
        raise ValueError('Can only construct tree from group, project, session, analysis or acquisition level')

    analysis_id     = None
    acquisition_id  = None
    session_id      = None
    project_id      = None
    group_id        = None
    tree            = {}

    if cont_name == 'analysis':
        analysis_id = bson.ObjectId(_id)
        analysis = get_container('analysis', analysis_id)
        tree['analysis'] = analysis
        if analysis['parent']['type'] == 'session':
            session_id = analysis['parent']['id']
    if cont_name == 'acquisition':
        acquisition_id = bson.ObjectId(_id)
        acquisition = get_container('acquisition', acquisition_id)
        tree['acquisition'] = acquisition
        session_id = acquisition['session']
    if cont_name == 'session' or session_id:
        if not session_id:
            session_id = bson.ObjectId(_id)
        session = get_container('session', session_id)
        tree['session'] = session
        subject = session.get('subject')
        if subject:
            tree['subject'] = subject
        project_id = session['project']
    if cont_name == 'project' or project_id:
        if not project_id:
            project_id = bson.ObjectId(_id)
        project = get_container('project', project_id)
        tree['project'] = project
        group_id = project['group']
    if cont_name == 'group' or group_id:
        if not group_id:
            group_id = _id
        tree['group'] = get_container('group', group_id)

    return tree


def is_session_compliant(session, template):
    """
    Given a project-level session template and a session,
    returns True/False if the session is in compliance with the template
    """

    def check_req(cont, req_k, req_v):
        """
        Return True if container satisfies specific requirement.
        """
        cont_v = cont.get(req_k)
        if cont_v:
            if isinstance(req_v, dict):
                for k,v in req_v.iteritems():
                    if not check_req(cont_v, k, v):
                        return False
            elif isinstance(cont_v, list):
                found_in_list = False
                for v in cont_v:
                    if re.search(req_v, v, re.IGNORECASE):
                        found_in_list = True
                        break
                if not found_in_list:
                    return False
            else:
                # Assume regex for now
                if not re.search(req_v, cont_v, re.IGNORECASE):
                    return False
        else:
            return False
        return True


    def check_cont(cont, reqs):
        """
        Return True if container satisfies requirements.
        Return False otherwise.
        """
        for req_k, req_v in reqs.iteritems():
            if req_k == 'files':
                for fr in req_v:
                    fr_temp = fr.copy() #so subsequent calls don't have their minimum missing
                    min_count = fr_temp.pop('minimum')
                    count = 0
                    for f in cont.get('files', []):
                        if 'deleted' in f or not check_cont(f, fr_temp):
                            # Didn't find a match, on to the next one
                            continue
                        else:
                            count += 1
                            if count >= min_count:
                                break
                    if count < min_count:
                        return False

            else:
                if not check_req(cont, req_k, req_v):
                    return False
        return True


    s_requirements = template.get('session')
    a_requirements = template.get('acquisitions')

    if s_requirements:
        if not check_cont(session, s_requirements):
            return False

    if a_requirements:
        if not session.get('_id'):
            # New session, won't have any acquisitions. Compliance check fails
            return False
        acquisitions = list(config.db.acquisitions.find({'session': session['_id'], 'deleted': {'$exists': False}}))
        for req in a_requirements:
            req_temp = copy.deepcopy(req)
            min_count = req_temp.pop('minimum')
            count = 0
            for a in acquisitions:
                if not check_cont(a, req_temp):
                    # Didn't find a match, on to the next one
                    continue
                else:
                    count += 1
                    if count >= min_count:
                        break
            if count < min_count:
                return False
    return True

def upsert_fileinfo(cont_name, _id, fileinfo, ignore_hash_replace=False):

    cont_name = containerutil.pluralize(cont_name)
    _id = bson.ObjectId(_id)

    container_before = config.db[cont_name].find_one({'_id': _id})
    container_after = None
    saved_state = 'saved'


    # Look to see if file with the same name already exists in the container
    for f in container_before.get('files',[]):

        # File already exists, respond accordingly
        if f['name'] == fileinfo['name']:

            # If the existing file is deleted, always replace (But this is not considered a "replaced" saved state)
            if 'deleted' in f:
                remove_file(cont_name, _id, fileinfo['name'])
                container_after = add_file(cont_name, _id, fileinfo)
                saved_state = 'saved'


            # Files from a failed job should never replaced existing files that are "accepted" (unless they are deleted)
            elif fileinfo.get('from_failed_job') and not f.get('from_failed_job'):
                saved_state = 'ignored'

            # The file object is the same as an existing file and the caller has chosen to ignore in this situation
            elif f.get('hash') == fileinfo['hash'] and ignore_hash_replace:
                saved_state = 'ignored'

            # No special circumstances, proceed with a replace
            else:
                container_after = replace_file(cont_name, _id, f, fileinfo)
                saved_state = 'replaced'

            break


    else:

        # File was not already in container, add as normal
        container_after = add_file(cont_name, _id, fileinfo)

    return container_before, container_after, saved_state


def add_file(cont_name, _id, fileinfo):
    return config.db[cont_name].find_one_and_update(
        {'_id': _id},
        {'$push': {'files': fileinfo}},
        return_document=pymongo.collection.ReturnDocument.AFTER
    )

def replace_file(cont_name, _id, existing_fileinfo, fileinfo):

    while True:

        # Update the version and add existing file to "other_versions" list
        fileinfo['version'] = existing_fileinfo['version']+1
        fileinfo['other_versions'] = existing_fileinfo.pop('other_versions', [])
        fileinfo['other_versions'].append(existing_fileinfo)

        # Only update if the existing file has not changed since last load
        result = config.db[cont_name].replace_one(
            {'_id': _id, 'files': {'$elemMatch': {
                'name': fileinfo['name'],
                'modified': existing_fileinfo['modified'],
                'version': existing_fileinfo['version']}}},
            fileinfo
        )

        if not result.modified_count:
            # The existing file must have changed, grab update from db
            c = config.db[cont_name].find_one({'_id': _id, 'files.name': fileinfo['name']})
            for f in c.get('files'):
                if f['name'] == fileinfo['name']:
                    existing_fileinfo = f
                    break
            else:
                # The file wasn't found, must have been removed
                fileinfo['version'] = 1
                return add_file(cont_name, _id, fileinfo)

        return fileinfo



def remove_file(cont_name, _id, filename):
    return config.db[cont_name].find_one_and_update(
        {'_id': _id, 'files.name': filename},
        {'$pull': {'files': {'name': filename}}},
        return_document=pymongo.collection.ReturnDocument.AFTER
    )


def _group_id_fuzzy_match(group_id, project_label):
    existing_group_ids = [g['_id'] for g in config.db.groups.find(None, ['_id'])]
    if group_id.lower() in existing_group_ids:
        return group_id.lower(), project_label
    group_id_matches = difflib.get_close_matches(group_id, existing_group_ids, cutoff=0.8)
    if len(group_id_matches) == 1:
        group_id = group_id_matches[0]
    else:
        if group_id != '' or project_label != '':
            project_label = group_id + '_' + project_label
        group_id = 'unknown'
    return group_id, project_label

def _find_or_create_destination_project(group_id, project_label, timestamp, user):
    group_id, project_label = _group_id_fuzzy_match(group_id, project_label)
    group = config.db.groups.find_one({'_id': group_id})

    if project_label == '':
        project_label = 'Unknown'

    project_regex = '^'+re.escape(project_label)+'$'
    project = config.db.projects.find_one({'group': group['_id'], 'label': {'$regex': project_regex, '$options': 'i'}, 'deleted': {'$exists': False}})

    if project:
        # If the project already exists, check the user's access
        if user and not has_access(user, project, 'rw'):
            raise APIPermissionException('User {} does not have read-write access to project {}'.format(user, project['label']))
        return project

    else:
        # if the project doesn't exit, check the user's access at the group level
        if user and not has_access(user, group, 'rw'):
            raise APIPermissionException('User {} does not have read-write access to group {}'.format(user, group_id))

        project = {
                'group': group['_id'],
                'label': project_label,
                'permissions': group['permissions'],
                'public': False,
                'created': timestamp,
                'modified': timestamp
        }
        result = ContainerStorage.factory('project').create_el(project)
        project['_id'] = result.inserted_id
    return project

def _create_query(cont, cont_type, parent_type, parent_id, upload_type):
    if upload_type == 'label':
        q = {}
        q['label'] = cont['label']
        q[parent_type] = bson.ObjectId(parent_id)
        if cont_type == 'session' and cont.get('subject',{}).get('code'):
            q['subject.code'] = cont['subject']['code']
        return q
    elif upload_type == 'uid':
        return {
            parent_type : bson.ObjectId(parent_id),
            'uid': cont['uid']
        }
    else:
        raise NotImplementedError('upload type {} is not handled by _create_query'.format(upload_type))

def _upsert_container(cont, cont_type, parent, parent_type, upload_type, timestamp):
    cont['modified'] = timestamp

    if cont.get('timestamp'):
        cont['timestamp'] = dateutil.parser.parse(cont['timestamp'])

        if cont_type == 'acquisition':
            session_operations = {'$min': dict(timestamp=cont['timestamp'])}
            if cont.get('timezone'):
                session_operations['$set'] = {'timezone': cont['timezone']}
            config.db.sessions.update_one({'_id': parent['_id']}, session_operations)

    if cont_type == 'session':
        cont['subject'] = containerutil.add_id_to_subject(cont.get('subject'), parent['_id'])

    query = _create_query(cont, cont_type, parent_type, parent['_id'], upload_type)

    if config.db[cont_type+'s'].find_one(query) is not None:
        return _update_container_nulls(query, cont, cont_type)

    else:
        insert_vals = {
            parent_type:    parent['_id'],
            'permissions':  parent['permissions'],
            'public':       parent.get('public', False),
            'created':      timestamp
        }
        if cont_type == 'session':
            insert_vals['group'] = parent['group']
        cont.update(insert_vals)
        insert_id = config.db[cont_type+'s'].insert(cont)
        cont['_id'] = insert_id
        return cont


def _get_targets(project_obj, session, acquisition, type_, timestamp):
    target_containers = []
    if not session:
        return target_containers
    session_files = dict_fileinfos(session.pop('files', []))

    subject_files = []
    if session.get('subject'):
        subject_files = dict_fileinfos(session['subject'].pop('files', []))

    session_obj = _upsert_container(session, 'session', project_obj, 'project', type_, timestamp)
    target_containers.append(
        (TargetContainer(session_obj, 'session'), session_files)
    )

    if len(subject_files) > 0:
        target_containers.append(
            (TargetContainer(session_obj, 'subject'), subject_files)
        )

    if not acquisition:
        return target_containers
    acquisition_files = dict_fileinfos(acquisition.pop('files', []))
    acquisition_obj = _upsert_container(acquisition, 'acquisition', session_obj, 'session', type_, timestamp)
    target_containers.append(
        (TargetContainer(acquisition_obj, 'acquisition'), acquisition_files)
    )
    return target_containers


def find_existing_hierarchy(metadata, type_='uid', user=None):
    #pylint: disable=unused-argument
    project = metadata.get('project', {})
    session = metadata.get('session', {})
    acquisition = metadata.get('acquisition', {})

    # Fail if some fields are missing
    try:
        acquisition_uid = acquisition['uid']
        session_uid = session['uid']
    except Exception as e:
        log.error(metadata)
        raise APIStorageException(str(e))

    # Confirm session and acquisition exist
    session_obj = config.db.sessions.find_one({'uid': session_uid, 'deleted': {'$exists': False}}, ['project', 'permissions'])

    if session_obj is None:
        raise APINotFoundException('Session with uid {} does not exist'.format(session_uid))
    if user and not has_access(user, session_obj, 'rw'):
        raise APIPermissionException('User {} does not have read-write access to session {}'.format(user, session_uid))

    a = config.db.acquisitions.find_one({'uid': acquisition_uid, 'deleted': {'$exists': False}}, ['_id'])
    if a is None:
        raise APINotFoundException('Acquisition with uid {} does not exist'.format(acquisition_uid))

    now = datetime.datetime.utcnow()
    project_files = dict_fileinfos(project.pop('files', []))
    project_obj = config.db.projects.find_one({'_id': session_obj['project'], 'deleted': {'$exists': False}}, projection=PROJECTION_FIELDS + ['name'])
    target_containers = _get_targets(project_obj, session, acquisition, type_, now)
    target_containers.append(
        (TargetContainer(project_obj, 'project'), project_files)
    )
    return target_containers


def upsert_bottom_up_hierarchy(metadata, type_='uid', user=None):
    group = metadata.get('group', {})
    project = metadata.get('project', {})
    session = metadata.get('session', {})
    acquisition = metadata.get('acquisition', {})

    # Fail if some fields are missing
    try:
        _ = group['_id']
        _ = project['label']
        _ = acquisition['uid']
        session_uid = session['uid']
    except Exception as e:
        log.error(metadata)
        raise APIStorageException(str(e))

    session_obj = config.db.sessions.find_one({'uid': session_uid, 'deleted': {'$exists': False}})
    if session_obj: # skip project creation, if session exists

        if user and not has_access(user, session_obj, 'rw'):
            raise APIPermissionException('User {} does not have read-write access to session {}'.format(user, session_uid))

        now = datetime.datetime.utcnow()
        project_files = dict_fileinfos(project.pop('files', []))
        project_obj = config.db.projects.find_one({'_id': session_obj['project'], 'deleted': {'$exists': False}}, projection=PROJECTION_FIELDS + ['name'])
        target_containers = _get_targets(project_obj, session, acquisition, type_, now)
        target_containers.append(
            (TargetContainer(project_obj, 'project'), project_files)
        )
        return target_containers
    else:
        return upsert_top_down_hierarchy(metadata, type_=type_, user=user)


def upsert_top_down_hierarchy(metadata, type_='label', user=None):
    group = metadata['group']
    project = metadata['project']
    session = metadata.get('session')
    acquisition = metadata.get('acquisition')

    now = datetime.datetime.utcnow()
    project_files = dict_fileinfos(project.pop('files', []))
    project_obj = _find_or_create_destination_project(group['_id'], project['label'], now, user)
    target_containers = _get_targets(project_obj, session, acquisition, type_, now)
    target_containers.append(
        (TargetContainer(project_obj, 'project'), project_files)
    )
    return target_containers


def dict_fileinfos(infos):
    dict_infos = {}
    for info in infos:
        dict_infos[info['name']] = info
    return dict_infos


def update_container_hierarchy(metadata, cid, container_type):
    c_metadata = metadata.get(container_type)

    if c_metadata is None:
        c_metadata = {}

    now = datetime.datetime.utcnow()
    if c_metadata.get('timestamp'):
        c_metadata['timestamp'] = dateutil.parser.parse(c_metadata['timestamp'])
    c_metadata['modified'] = now
    c_obj = _update_container_nulls({'_id': cid}, c_metadata, container_type)
    if c_obj is None:
        raise APIStorageException('container does not exist')
    if container_type in ['session', 'acquisition']:
        _update_hierarchy(c_obj, container_type, metadata)
    return c_obj

def _update_hierarchy(container, container_type, metadata):
    project_id = container.get('project') # for sessions
    now = datetime.datetime.utcnow()

    if container_type == 'acquisition':
        session = metadata.get('session', {})
        session_obj = None
        if session.keys():
            session['modified'] = now
            if session.get('timestamp'):
                session['timestamp'] = dateutil.parser.parse(session['timestamp'])
            session_obj = _update_container_nulls({'_id': container['session']},  session, 'sessions')
        if session_obj is None:
            session_obj = get_container('session', container['session'])
        project_id = session_obj['project']

    if project_id is None:
        raise APIStorageException('Failed to find project id in session obj')
    project = metadata.get('project', {})
    if project.keys():
        project['modified'] = now
        _update_container_nulls({'_id': project_id}, project, 'projects')

def _update_container_nulls(base_query, update, container_type):
    coll_name = container_type if container_type.endswith('s') else container_type+'s'
    cont = config.db[coll_name].find_one(base_query)
    if cont is None:
        raise APIStorageException('Failed to find {} object using the query: {}'.format(container_type, base_query))

    bulk = config.db[coll_name].initialize_unordered_bulk_op()

    if update.get('metadata') and not cont.get('metadata'):
        # If we are trying to update metadata fields and the container metadata does not exist or is empty,
        # metadata can all be updated at once for efficiency
        m_update = util.mongo_sanitize_fields(update.pop('metadata'))
        bulk.find(base_query).update_one({'$set': {'metadata': m_update}})

    update_dict = util.mongo_dict(update)
    for k,v in update_dict.items():
        q = {}
        q.update(base_query)
        q['$or'] = [{k: {'$exists': False}}, {k: None}]
        u = {'$set': {k: v}}
        bulk.find(q).update_one(u)
    bulk.execute()
    return config.db[coll_name].find_one(base_query)


# NOTE skip coverage since this function is currently not used
def merge_fileinfos(parsed_files, infos): # pragma: no cover
    """it takes a dictionary of "hard_infos" (file size, hash)
    merging them with infos derived from a list of infos on the same or on other files
    """
    merged_files = {}
    for info in infos:
        parsed = parsed_files.get(info['name'])
        if parsed:
            path = parsed.path
            new_infos = copy.deepcopy(parsed.info)
        else:
            path = None
            new_infos = {}
        new_infos.update(info)
        merged_files[info['name']] = files.ParsedFile(new_infos, path)
    return merged_files
