# @author:  Gunnar Schaefer

import logging
log = logging.getLogger('scitran.api')

import bson

import scitran.data.medimg

import util
import containers

SESSION_POST_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Session',
    'type': 'object',
    'properties': {
        'label': {
            'type': 'string',
            'maxLength': 32,
        },
        'timestamp': {
            'type': 'string',
            'format': 'date-time',
        },
        'timezone': {
            'type': 'string',
            'enum': util.valid_timezones,
        },
    },
    'required': ['label'],
}

SESSION_PUT_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Session',
    'type': 'object',
    'properties': {
        'label': {
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
        'subject_code': {
            'type': 'string',
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

    post_schema = SESSION_POST_SCHEMA

    def __init__(self, request=None, response=None):
        super(Sessions, self).__init__(request, response)
        self.dbc = self.app.db.sessions

    def count(self):
        """Return the number of Sessions."""
        self.response.write(self.dbc.count())

    def post(self, pid):
        """Create a new Session."""
        json_body = self._post()
        _id = bson.ObjectId(pid)
        project = self.app.db.projects.find_one({'_id': _id}, ['group', 'permissions', 'public'])
        if not project:
            self.abort(404, 'no such project')
        if not self.superuser_request and util.user_perm(project['permissions'], self.uid).get('access') != 'admin':
            self.abort(400, 'must be project admin to create session')
        json_body['project'] = _id
        json_body['group'] = project['group']
        json_body['permissions'] = project['permissions']
        json_body['public'] = project.get('public', False)
        json_body['files'] = []
        if 'timestamp' in json_body:
            json_body['timestamp'] = util.parse_timestamp(json_body['timestamp'])
        return {'_id': str(self.dbc.insert(json_body))}

    def get(self, pid=None, gid=None):
        """Return the list of project or group sessions."""
        if pid is not None:
            _id = bson.ObjectId(pid)
            if not self.app.db.projects.find_one({'_id': _id}):
                self.abort(404, 'no such project')
            query = {'project': _id}
        elif gid is not None:
            if not self.app.db.groups.find_one({'_id': gid}):
                self.abort(404, 'no such group')
            query = {'group': gid}
        else:
            self.abort(400) # the routing table should never allow this
        projection = {'label': 1, 'subject.code': 1, 'notes': 1, 'project': 1, 'group': 1, 'timestamp': 1, 'timezone': 1}
        sessions = self._get(query, projection, self.request.get('admin').lower() in ('1', 'true'))
        for sess in sessions:
            sess['project'] = str(sess['project'])
            sess['subject_code'] = sess.pop('subject', {}).get('code', '') # FIXME when subject is pulled out of session
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
        sess['subject_code'] = sess.get('subject', {}).get('code', '') # FIXME when subject is pulled out of session
        if self.debug:
            sess['debug'] = {}
            sess['debug']['project'] = self.uri_for('project', sess['project'], _full=True) + '?' + self.request.query_string
            sess['debug']['acquisitions'] = self.uri_for('acquisitions', sid, _full=True) + '?' + self.request.query_string
        return sess

    def put(self, sid):
        """Update an existing Session."""
        # FIXME should use super(Session, self)._put(_id)
        _id = bson.ObjectId(sid)
        json_body = self.validate_json_body(_id, ['project'])
        if 'subject_code' in json_body: # FIXME delete with subject is pulled out of session
            json_body['subject.code'] = json_body.pop('subject_code')
        if 'project' in json_body:
            session, _ = self._get(_id, 'admin', perm_only=False)
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
        _id = bson.ObjectId(sid)
        self._get(_id, 'admin', perm_only=True)
        acq_ids = [a['_id'] for a in self.app.db.acquisitions.find({'session': _id}, [])]
        if acq_ids:
            self.abort(400, 'session contains acquisitions and cannot be deleted')
        self._delete(_id)
