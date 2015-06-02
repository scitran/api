# @author:  Gunnar Schaefer

import logging
log = logging.getLogger('scitran.api')

import bson.json_util

import scitran.data.medimg

import containers

SESSION_PUT_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Session',
    'type': 'object',
    'properties': {
        'name': {
            'title': 'Name',
            'type': 'string',
            'maxLength': 32,
        },
        'notes': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'author': {
                        'type': 'string',
                    },
                    'timestamp': {
                        'type': 'string',
                        'format': 'date-time',
                    },
                    'text': {
                        'type': 'string',
                    },
                },
                'required': ['text'],
                'additionalProperties': False,
            },
        },
        'project': {
            'type': 'string',
            'pattern': '^[0-9a-f]{24}$',
        },
        'subject': {
            'title': 'Subject',
            'type': 'object',
            'properties': {
                'code': {
                    'title': 'Code',
                    'type': 'string',
                },
            },
        },
    },
    'minProperties': 1,
    'additionalProperties': False,
}


class Sessions(containers.ContainerList):

    """/sessions """

    def __init__(self, request=None, response=None):
        super(Sessions, self).__init__(request, response)
        self.dbc = self.app.db.sessions

    def count(self):
        """Return the number of Sessions."""
        self.response.write(self.dbc.count())

    def post(self):
        """Create a new Session"""
        self.response.write('sessions post\n')

    def get(self, pid=None):
        """Return the list of Project Sessions."""
        if pid is not None:
            _id = bson.ObjectId(pid)
            if not self.app.db.projects.find_one({'_id': _id}):
                self.abort(404, 'no such Project')
            query = {'project': _id}
        else:
            query = {}
        if self.request.get('group'):
            query['group'] = self.request.get('group')
        projection = {'label': 1, 'subject.code': 1, 'notes': 1, 'project': 1, 'group': 1, 'timestamp': 1, 'timezone': 1}
        sessions = self._get(query, projection, self.request.get('admin').lower() in ('1', 'true'))
        for sess in sessions:
            sess['project'] = str(sess['project'])
        if self.debug:
            for sess in sessions:
                sid = str(sess['_id'])
                sess['debug'] = {}
                sess['debug']['group'] = self.uri_for('group', sess['group'], _full=True) + '?' + self.request.query_string
                sess['debug']['project'] = self.uri_for('project', sess['project'], _full=True) + '?' + self.request.query_string
                sess['debug']['details'] = self.uri_for('session', sid, _full=True) + '?' + self.request.query_string
                sess['debug']['acquisitions'] = self.uri_for('acquisitions', sid, _full=True) + '?' + self.request.query_string
        return sessions

    def put(self):
        """Update many Sessions."""
        self.response.write('sessions put\n')


class Session(containers.Container):

    """/sessions/<sid> """

    json_schema = {
        '$schema': 'http://json-schema.org/draft-04/schema#',
        'title': 'Session',
        'type': 'object',
        'properties': {
            '_id': {
            },
            'project': {
            },
            'files': {
                'title': 'Files',
                'type': 'array',
                'items': containers.FILE_SCHEMA,
                'uniqueItems': True,
            },
        },
        'required': ['_id', 'project', 'uid', 'patient_id', 'subject'], #FIXME
    }

    put_schema = SESSION_PUT_SCHEMA

    def __init__(self, request=None, response=None):
        super(Session, self).__init__(request, response)
        self.dbc = self.app.db.sessions

    def schema(self, *args, **kwargs):
        method =self.request.get('method').lower()
        if method == 'put':
            return SESSION_PUT_SCHEMA
        return super(Session, self).schema(scitran.data.medimg.medimg.MedImgReader.session_properties)

    def get(self, sid):
        """Return one Session, conditionally with details."""
        _id = bson.ObjectId(sid)
        sess, _ = self._get(_id)
        sess['project'] = str(sess['project'])
        if self.debug:
            sess['debug'] = {}
            sess['debug']['project'] = self.uri_for('project', sess['project'], _full=True) + '?' + self.request.query_string
            sess['debug']['acquisitions'] = self.uri_for('acquisitions', sid, _full=True) + '?' + self.request.query_string
        return sess

    def put(self, sid):
        """Update an existing Session."""
        _id = bson.ObjectId(sid)
        json_body = self.validate_json_body(_id, ['project'])
        if 'project' in json_body:
            session, user_perm = self._get(_id, 'admin', perm_only=False)
            self._get(session['project'], 'admin', perm_only=True, dbc=self.app.db.projects, dbc_name='Project')
            destination, dest_user_perm = self._get(json_body['project'], 'admin', perm_only=False, dbc=self.app.db.projects, dbc_name='Project')
            json_body['permissions'] = destination['permissions']
            json_body['group'] = destination['group']
            self.update_db(_id, json_body)
            self.app.db.acquisitions.update({'session': _id}, {'$set': {'permissions': destination['permissions']}}, multi=True)
        else:
            self._get(_id, 'admin' if 'permissions' in json_body else 'rw', perm_only=True)
            self.update_db(_id, json_body)

    def delete(self, sid):
        """Delete a Session."""
        self.abort(501)
