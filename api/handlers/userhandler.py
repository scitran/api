import base64
import datetime
import pymongo
import os

from .. import base
from .. import util
from .. import config
from .. import validators
from ..auth import userauth
from ..dao import containerstorage
from ..dao import noop, APIStorageException

log = config.log


class UserHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(UserHandler, self).__init__(request, response)
        self.storage = containerstorage.ContainerStorage('users', use_object_id=False)

    def get(self, _id):
        user = self._get_user(_id)
        permchecker = userauth.default(self, user)
        result = permchecker(self.storage.exec_op)('GET', _id, projection={'api_key': 0} or None)
        if result is None:
            self.abort(404, 'User does not exist')
        return result

    def self(self):
        """Return details for the current User."""
        if not self.uid:
            self.abort(400, 'no user is logged in')
        user = self.storage.exec_op('GET', self.uid)
        if not user:
            self.abort(403, 'user does not exist')
        return user

    def get_all(self):
        permchecker = userauth.list_permission_checker(self)
        result = permchecker(self.storage.exec_op)('GET', projection={'preferences': 0, 'api_key': 0})
        if result is None:
            self.abort(404, 'Not found')
        return result

    def delete(self, _id):
        user = self._get_user(_id)
        permchecker = userauth.default(self, user)
        # Check for authZ before cleaning up user permissions
        permchecker(noop)('DELETE', _id)
        self._cleanup_user_permissions(user.get('_id'))
        log.debug('2')
        result = self.storage.exec_op('DELETE', _id)
        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'User {} not removed'.format(_id))
        return result

    def put(self, _id):
        """
        .. http:put:: /api/users/(uid)

            Update user

            :query root: explain...

            :param uid: User ID (email address)
            :type uid: string

            :reqheader Authorization: required OAuth session token

            **Example request**:

            .. sourcecode:: http

                PUT /api/users/jdoe@gmail.com?root=true HTTP/1.1
                Host: demo.flywheel.io
                Authorization: ya29..a356DasssSFG_FEbggasr435g54GG$33DFGSssghnj-HSsdfgs450nvsASAPinZCXVqertt
                Content-Type: application/json;charset=UTF-8
                {"firstname":"John","lastname":"Doe","email":"jdoe@gmail.com","root":true}

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json; charset=utf-8
                Content-Length: 15
                {"modified": 1}

        """
        user = self._get_user(_id)
        permchecker = userauth.default(self, user)
        payload = self.request.json_body
        mongo_schema_uri = validators.schema_uri('mongo', 'user.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', 'user.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'PUT')
        payload['modified'] = datetime.datetime.utcnow()
        result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'User {} not updated'.format(_id))

    def post(self):
        """
        .. http:post:: /api/users

            Add user
            :query root: explain...

            :reqheader Authorization: required OAuth session token

            **Example request**:

            .. sourcecode:: http

                POST /api/users?root=true HTTP/1.1
                Host: demo.flywheel.io
                Authorization: ya29..a356DasssSFG_FEbggasr435g54GG$33DFGSssghnj-HSsdfgs450nvsASAPinZCXVqertt
                Content-Type: application/json;charset=UTF-8
                {"_id":"jane.doe@gmail.com","firstname":"Jane","lastname":"Doe","email":"jane.doe@gmail.com"}

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json; charset=utf-8
                Vary: Accept-Encoding
                {"_id": "jane.doe@gmail.com"}

        """

        permchecker = userauth.default(self)
        payload = self.request.json_body
        mongo_schema_uri = validators.schema_uri('mongo', 'user.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', 'user.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'POST')
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        payload['root'] = payload.get('root', False)
        payload.setdefault('email', payload['_id'])
        payload.setdefault('avatars', {})
        result = mongo_validator(permchecker(self.storage.exec_op))('POST', payload=payload)
        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(404, 'User {} not updated'.format(payload['_id']))

    def _cleanup_user_permissions(self, uid):
        try:
            config.db.collections.delete_many({'curator': uid})
            config.db.groups.update_many({'roles._id': uid}, {'$pull': {'roles' : {'_id': uid}}})

            query = {'permissions._id': uid}
            update = {'$pull': {'permissions' : {'_id': uid}}}
            config.db.projects.update_many(query, update)
            config.db.sessions.update_many(query, update)
            config.db.acquisitions.update_many(query, update)
        except APIStorageException:
            self.abort(500, 'Site-wide user permissions for {} were unabled to be removed'.format(uid))

    def avatar(self, uid):
        self.resolve_avatar(uid, default=self.request.GET.get('default'))

    def self_avatar(self):
        if self.uid is None:
            self.abort(404, 'not a logged-in user')
        self.resolve_avatar(self.uid, default=self.request.GET.get('default'))

    def resolve_avatar(self, email, default=None):
        """
        Given an email, redirects to their avatar.
        On failure, either 404s or redirects to default, if provided.
        """

        # Storage throws a 404; we want to catch that and handle it separately in the case of a provided default.
        try:
            user = self._get_user(email)
        except APIStorageException:
            user = {}

        avatar  = user.get('avatar', None)

        # If the user exists but has no set avatar, try to get one
        if user and avatar is None:
            gravatar = util.resolve_gravatar(email)

            if gravatar is not None:
                user = config.db['users'].find_one_and_update({
                        '_id': email,
                    }, {
                        '$set': {
                            'avatar': gravatar,
                            'avatars.gravatar': gravatar,
                        }
                    },
                    return_document=pymongo.collection.ReturnDocument.AFTER
                )

        if user.get('avatar', None):
            # Our data is unicode, but webapp2 wants a python-string for its headers.
            self.redirect(str(user['avatar']), code=307)
        elif default is not None:
            self.redirect(str(default), code=307)
        else:
            self.abort(404, 'no avatar')

    def generate_api_key(self):
        if not self.uid:
            self.abort(400, 'no user is logged in')
        generated_key = base64.urlsafe_b64encode(os.urandom(42))
        now = datetime.datetime.utcnow()
        payload = {'api_key': {'key': generated_key, 'created': now, 'last_used': None}}
        result = self.storage.exec_op('PUT', _id=self.uid, payload=payload)
        if result.modified_count == 1:
            return {'key': generated_key}
        else:
            self.abort(500, 'New key for user {} not generated'.format(self.uid))

    def _get_user(self, _id):
        user = self.storage.get_container(_id)
        if user is not None:
            return user
        else:
            self.abort(404, 'user {} not found'.format(_id))
