import bson.objectid

from . import APIPermissionException
from .. import config
from ..auth import has_access


CONT_TYPES = ['acquisition', 'analysis', 'collection', 'group', 'project', 'session']
SINGULAR_TO_PLURAL = {
    'group':       'groups',
    'project':     'projects',
    'session':     'sessions',
    'acquisition': 'acquisitions',
    'collection':  'collections',
    'analysis':    'analyses',
}
PLURAL_TO_SINGULAR = {p: s for s, p in SINGULAR_TO_PLURAL.iteritems()}


def add_id_to_subject(subject, pid):
    """
    Add a mongo id field to given subject object (dict)

    Use the same _id as other subjects in the session's project with the same code
    If no _id is found, generate a new _id
    """
    result = None
    if subject is None:
        subject = {}
    if subject.get('_id') is not None: # cover 100
        # Ensure _id is bson ObjectId
        subject['_id'] = bson.ObjectId(str(subject['_id']))
        return subject

    # Attempt to match with another session in the project
    if subject.get('code') is not None and pid is not None:
        query = {'subject.code': subject['code'],
                 'project': pid,
                 'subject._id': {'$exists': True}}
        result = config.db.sessions.find_one(query)

    if result is not None:
        subject['_id'] = result['subject']['_id']
    else:
        subject['_id'] = bson.ObjectId()
    return subject

def get_stats(cont, cont_type):
    """
    Add a session, subject, non-compliant session and attachment count to a project or collection
    """

    if cont_type not in ['projects', 'collections']:
        return cont

    # Get attachment count from file array length
    cont['attachment_count'] = len(cont.get('files', []))

    # Get session and non-compliant session count
    match_q = {}
    if cont_type == 'projects':
        match_q = {'project': cont['_id'], 'archived': {'$in': [None, False]}}
    elif cont_type == 'collections':
        result = config.db.acquisitions.find({'collections': cont['_id'], 'archived': {'$in': [None, False]}}, {'session': 1})
        session_ids = list(set([s['session'] for s in result]))
        match_q = {'_id': {'$in': session_ids}}

    pipeline = [
        {'$match': match_q},
        {'$project': {'_id': 1, 'non_compliant':  {'$cond': [{'$eq': ['$satisfies_template', False]}, 1, 0]}}},
        {'$group': {'_id': 1, 'noncompliant_count': {'$sum': '$non_compliant'}, 'total': {'$sum': 1}}}
    ]

    result = config.db.command('aggregate', 'sessions', pipeline=pipeline).get('result', [])

    if len(result) > 0:
        cont['session_count'] = result[0].get('total', 0)
        cont['noncompliant_session_count'] = result[0].get('noncompliant_count', 0)
    else:
        # If there are no sessions, return zero'd out stats
        cont['session_count'] = 0
        cont['noncompliant_session_count'] = 0
        cont['subject_count'] = 0
        return cont

    # Get subject count
    match_q['subject._id'] = {'$ne': None}
    pipeline = [
        {'$match': match_q},
        {'$group': {'_id': '$subject._id'}},
        {'$group': {'_id': 1, 'count': { '$sum': 1 }}}
    ]

    result = config.db.command('aggregate', 'sessions', pipeline=pipeline).get('result', [])

    if len(result) > 0:
        cont['subject_count'] = result[0].get('count', 0)
    else: # cover 100
        cont['subject_count'] = 0

    return cont


class ContainerReference(object):
    # pylint: disable=redefined-builtin
    # TODO: refactor to resolve pylint warning

    def __init__(self, type, id):
        if type not in CONT_TYPES: # cover 100
            raise Exception('Container type must be one of {}'.format(CONT_TYPES))

        if not isinstance(type, basestring): # cover 100
            raise Exception('Container type must be of type str')
        if not isinstance(id, basestring): # cover 100
            raise Exception('Container id must be of type str')

        self.type = type
        self.id = id

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other): # cover 100
        return not self.__dict__ == other.__dict__

    @classmethod
    def from_dictionary(cls, d):
        return cls(
            type = d['type'],
            id = d['id']
        )

    @classmethod
    def from_filereference(cls, fr):
        return cls(
            type = fr.type,
            id = fr.id
        )

    def get(self):
        collection = pluralize(self.type)
        result = config.db[collection].find_one({'_id': bson.ObjectId(self.id)})
        if result is None: # cover 100
            raise Exception('No such {} {} in database'.format(self.type, self.id))
        if 'parent' in result: # cover 100
            parent_collection = pluralize(result['parent']['type'])
            parent = config.db[parent_collection].find_one({'_id': bson.ObjectId(result['parent']['id'])})
            if parent is None:
                raise Exception('Cannot find parent {} {} of {} {}'.format(
                    result['parent']['type'], result['parent']['id'], self.type, self.id))
            result['permissions'] = parent['permissions']
        return result

    def find_file(self, filename):
        cont = self.get()
        for f in cont.get('files', []):
            if f['name'] == filename:
                return f
        return None

    def file_uri(self, filename):
        collection = pluralize(self.type)
        cont = self.get()
        if 'parent' in cont: # cover 100
            par_coll, par_id = pluralize(cont['parent']['type']), cont['parent']['id']
            return '/{}/{}/{}/{}/files/{}'.format(par_coll, par_id, collection, self.id, filename)
        return '/{}/{}/files/{}'.format(collection, self.id, filename)

    def check_access(self, uid, perm_name):
        cont = self.get()
        if has_access(uid, cont, perm_name):
            return
        else:
            raise APIPermissionException('User {} does not have {} access to {} {}'.format(uid, perm_name, self.type, self.id))


class FileReference(ContainerReference):
    # pylint: disable=redefined-builtin
    # TODO: refactor to resolve pylint warning

    def __init__(self, type, id, name):
        super(FileReference, self).__init__(type, id)
        self.name = name

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other): # cover 100
        return not self.__dict__ == other.__dict__

    @classmethod
    def from_dictionary(cls, d):
        return cls(
            type = d['type'],
            id = d['id'],
            name = d['name']
        )


def create_filereference_from_dictionary(d):
    return FileReference.from_dictionary(d)

def create_containerreference_from_dictionary(d):
    return ContainerReference.from_dictionary(d)

def create_containerreference_from_filereference(fr):
    return ContainerReference.from_filereference(fr)


def pluralize(cont_name):
    if cont_name in SINGULAR_TO_PLURAL:
        return SINGULAR_TO_PLURAL[cont_name]
    elif cont_name in PLURAL_TO_SINGULAR: # cover 100
        return cont_name
    raise ValueError('Could not pluralize unknown container name {}'.format(cont_name)) # cover 100

def singularize(cont_name):
    if cont_name in PLURAL_TO_SINGULAR:
        return PLURAL_TO_SINGULAR[cont_name]
    elif cont_name in SINGULAR_TO_PLURAL:
        return cont_name
    raise ValueError('Could not singularize unknown container name {}'.format(cont_name)) # cover 100
