# @author:  Gunnar Schaefer

import logging
log = logging.getLogger('scitran.api')

import jsonschema
import bson.json_util

import scitran.data.medimg

import util
import users
import containers

PROJECT_POST_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Project',
    'type': 'object',
    'properties': {
        'group': {
            'type': 'string',
        },
        'name': {
            'title': 'Name',
            'type': 'string',
            'maxLength': 32,
        },
    },
    'required': ['group', 'name'],
    'additionalProperties': False,
}

PROJECT_PUT_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Project',
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
        'permissions': {
            'title': 'Permissions',
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'access': {
                        'type': 'string',
                        'enum': [role['rid'] for role in users.ROLES],
                    },
                    '_id': {
                        'type': 'string',
                    },
                    'site': {
                        'type': 'string',
                    },
                },
                'required': ['access', '_id'],
                'additionalProperties': False,
            },
        },
        'public': {
            'title': 'Public',
            'type': 'boolean',
        },
    },
    'minProperties': 1,
    'additionalProperties': False,
}


class Projects(containers.ContainerList):

    """/projects """

    def __init__(self, request=None, response=None):
        super(Projects, self).__init__(request, response)
        self.dbc = self.app.db.projects

    def count(self):
        """Return the number of Projects."""
        self.response.write(self.dbc.count())

    def post(self):
        """Create a new Project."""
        try:
            json_body = self.request.json_body
            jsonschema.validate(json_body, PROJECT_POST_SCHEMA)
        except (ValueError, jsonschema.ValidationError) as e:
            self.abort(400, str(e))
        group = self.app.db.groups.find_one({'_id': json_body['group']}, ['roles'])
        if not group:
            self.abort(400, 'invalid group id')
        if not self.superuser_request and util.user_perm(group['roles'], self.uid).get('access') != 'admin':
            self.abort(400, 'must be group admin to create project')
        json_body['files'] = []
        json_body['permissions'] = group['roles']
        json_body['public'] = json_body.get('public', False)
        return {'_id': str(self.dbc.insert(json_body))}

    def get(self):
        """Return the User's list of Projects."""
        query = {'group': self.request.get('group')} if self.request.get('group') else {}
        projection = {'group': 1, 'name': 1, 'notes': 1, 'timestamp': 1, 'timezone': 1}
        projects = self._get(query, projection, self.request.get('admin').lower() in ('1', 'true'))
        if self.debug:
            for proj in projects:
                pid = str(proj['_id'])
                proj['debug'] = {}
                proj['debug']['group'] = self.uri_for('group', proj['group'], _full=True) + '?' + self.request.query_string
                proj['debug']['details'] = self.uri_for('project', pid, _full=True) + '?' + self.request.query_string
                proj['debug']['sessions'] = self.uri_for('p_sessions', pid, _full=True) + '?' + self.request.query_string
        return projects

    def groups(self):
        """Return the User's list of Project Groups."""
        group_ids = list(set((p['group'] for p in self.get())))
        return list(self.app.db.groups.find({'_id': {'$in': group_ids}}, ['name']))


class Project(containers.Container):

    """/projects/<pid> """

    json_schema = {
        '$schema': 'http://json-schema.org/draft-04/schema#',
        'title': 'Project',
        'type': 'object',
        'properties': {
            '_id': {
            },
            'permissions': {
                'title': 'Permissions',
                'type': 'object',
                'minProperties': 1,
            },
            'files': {
                'title': 'Files',
                'type': 'array',
                'items': containers.FILE_SCHEMA,
                'uniqueItems': True,
            },
        },
        'required': ['_id', 'group', 'name'], #FIXME
    }

    put_schema = PROJECT_PUT_SCHEMA

    def __init__(self, request=None, response=None):
        super(Project, self).__init__(request, response)
        self.dbc = self.app.db.projects

    def schema(self, *args, **kwargs):
        return super(Project, self).schema(scitran.data.medimg.medimg.MedImgReader.project_properties)

    def get(self, pid):
        """Return one Project, conditionally with details."""
        _id = bson.ObjectId(pid)
        proj, _ = self._get(_id)
        if self.debug:
            proj['debug'] = {}
            proj['debug']['sessions'] = self.uri_for('p_sessions', pid, _full=True) + '?' + self.request.query_string
        return proj

    def put(self, pid):
        """Update an existing Project."""
        _id = bson.ObjectId(pid)
        json_body = super(Project, self).put(_id)
        if 'permissions' in json_body or 'public' in json_body:
            updates = {}
            if 'permissions' in json_body:
                updates['permissions'] = json_body['permissions']
            if 'public' in json_body:
                updates['public'] = json_body['public']
            session_ids = [s['_id'] for s in self.app.db.sessions.find({'project': _id}, [])]
            self.app.db.sessions.update({'project': _id}, {'$set': updates}, multi=True)
            self.app.db.acquisitions.update({'session': {'$in': session_ids}}, {'$set': updates}, multi=True)

    def delete(self, pid):
        """Delete an Project."""
        self.abort(501)
