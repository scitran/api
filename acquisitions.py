# @author:  Gunnar Schaefer

import logging
log = logging.getLogger('scitran.api')

import bson.json_util

import scitran.data
import scitran.data.medimg

import containers

ACQUISITION_PUT_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Acquisition',
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
        'description': {
            'title': 'Description',
            'type': 'string'
        },
    },
    'minProperties': 1,
    'additionalProperties': False,
}


class Acquisitions(containers.ContainerList):

    """/nimsapi/acquisitions """

    def __init__(self, request=None, response=None):
        super(Acquisitions, self).__init__(request, response)
        self.dbc = self.app.db.acquisitions

    def count(self):
        """Return the number of Acquisitions."""
        self.response.write(self.dbc.count())

    def post(self):
        """Create a new Acquisition."""
        self.response.write('acquisitions post\n')

    def get(self, sid):
        """Return the list of Session Acquisitions."""
        _id = bson.ObjectId(sid)
        if not self.app.db.sessions.find_one({'_id': _id}):
            self.abort(404, 'no such Session')
        query = {'session': _id}
        projection = {'label': 1, 'description': 1, 'types': 1, 'notes': 1, 'timestamp': 1, 'timezone': 1}
        acquisitions = self._get(query, projection, self.request.get('admin').lower() in ('1', 'true'))
        if self.debug:
            for acquisition in acquisitions:
                aid = str(acquisition['_id'])
                acquisition['details'] = self.uri_for('acquisition', aid, _full=True) + '?' + self.request.query_string
        return acquisitions

    def put(self):
        """Update many Acquisitions."""
        self.response.write('acquisitions put\n')


class Acquisition(containers.Container):

    """/nimsapi/acquisitions/<aid> """

    json_schema = {
        '$schema': 'http://json-schema.org/draft-04/schema#',
        'title': 'Acquisition',
        'type': 'object',
        'properties': {
            '_id': {
            },
            'session': {
            },
            'files': {
                'title': 'Files',
                'type': 'array',
                'items': containers.FILE_SCHEMA,
                'uniqueItems': True,
            },
        },
        'required': ['_id'], #FIXME
    }

    put_schema = ACQUISITION_PUT_SCHEMA

    def __init__(self, request=None, response=None):
        super(Acquisition, self).__init__(request, response)
        self.dbc = self.app.db.acquisitions

    def schema(self, *args, **kwargs):
        return super(Acquisition, self).schema(scitran.data.medimg.medimg.MedImgReader.acquisition_properties)
        scitran.data.project_properties(ds_dict['project_type'])
        scitran.data.session_properties(ds_dict['session_type'])
        scitran.data.acquisition_properties(ds_dict['acquisition_type'])

    def get(self, aid):
        """Return one Acquisition, conditionally with details."""
        _id = bson.ObjectId(aid)
        acq, _ = self._get(_id)
        return acq

    def put(self, aid):
        """Update an existing Acquisition."""
        _id = bson.ObjectId(aid)
        json_body = super(Acquisition, self).put(_id)

    def delete(self, aid):
        """Delete an Acquisition."""
        self.abort(501)
