import base64
import datetime
import pymongo
import os

from ..web import base
from .. import util
from .. import config
from .. import validators
from ..auth import userauth, require_admin
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
        projection = {'api_key': 0}
        if not self.user_is_admin:
            projection['wechat'] = 0
        result = permchecker(self.storage.exec_op)('GET', _id, projection=projection or None)
        if result is None: # cover 100
            self.abort(404, 'User does not exist')
        return result

    def self(self):
        """Return details for the current User."""
        if not self.uid:
            self.abort(400, 'no user is logged in')
        user = self.storage.exec_op('GET', self.uid)
        if not user: # cover 100
            self.abort(403, 'user does not exist')
        return user

    def get_all(self):
        permchecker = userauth.list_permission_checker(self)
        projection = {'preferences': 0, 'api_key': 0}
        if not self.user_is_admin:
            projection['wechat'] = 0
        result = permchecker(self.storage.exec_op)('GET', projection=projection)
        if result is None: # cover 100
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
        else: # cover 100
            self.abort(404, 'User {} not removed'.format(_id))
        return result # cover 100

    @validators.verify_payload_exists
    def put(self, _id):
        """Update a user"""
        user = self._get_user(_id)
        permchecker = userauth.default(self, user)
        payload = self.request.json_body
        if not payload: # cover 100
            self.abort(400, 'PUT request body cannot be empty')
        mongo_schema_uri = validators.schema_uri('mongo', 'user.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', 'user-update.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'PUT')
        payload['modified'] = datetime.datetime.utcnow()
        result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else: # cover 100
            self.abort(404, 'User {} not updated'.format(_id))

    def post(self):
        """Add user"""
        permchecker = userauth.default(self)
        payload = self.request.json_body
        if self.is_true('wechat'): # cover 100
            payload['wechat'] = {'registration_code': base64.urlsafe_b64encode(os.urandom(42))}
        mongo_schema_uri = validators.schema_uri('mongo', 'user.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', 'user-new.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'POST')
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        payload['root'] = payload.get('root', False)
        payload.setdefault('email', payload['_id'])
        payload.setdefault('avatars', {})
        result = mongo_validator(permchecker(self.storage.exec_op))('POST', payload=payload)
        if result.acknowledged:
            return {'_id': result.inserted_id}
        else: # cover 100
            self.abort(404, 'User {} not updated'.format(payload['_id']))

    def _cleanup_user_permissions(self, uid):
        try:
            config.db.collections.delete_many({'curator': uid})
            config.db.groups.update_many({'permissions._id': uid}, {'$pull': {'permissions' : {'_id': uid}}})

            query = {'permissions._id': uid}
            update = {'$pull': {'permissions' : {'_id': uid}}}
            config.db.projects.update_many(query, update)
            config.db.sessions.update_many(query, update)
            config.db.acquisitions.update_many(query, update)
        except APIStorageException: # cover 100
            self.abort(500, 'Site-wide user permissions for {} were unabled to be removed'.format(uid))

    def avatar(self, uid):
        self.resolve_avatar(uid, default=self.request.GET.get('default'))

    def self_avatar(self):
        if self.uid is None: # cover 100
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
        except APIStorageException: # cover 100
            user = {}

        avatar  = user.get('avatar', None)

        # If the user exists but has no set avatar, try to get one
        if user and avatar is None:
            gravatar = util.resolve_gravatar(email)

            if gravatar is not None: # cover 100
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

        if user.get('avatar', None): # cover 100
            # Our data is unicode, but webapp2 wants a python-string for its headers.
            self.redirect(str(user['avatar']), code=307)
        elif default is not None: # cover 100
            self.redirect(str(default), code=307)
        else:
            self.abort(404, 'no avatar')

    def generate_api_key(self):
        if not self.uid:
            self.abort(400, 'no user is logged in')
        generated_key = util.create_nonce()
        now = datetime.datetime.utcnow()
        payload = {'api_key': {'key': generated_key, 'created': now, 'last_used': None}}
        result = self.storage.exec_op('PUT', _id=self.uid, payload=payload)
        if result.modified_count == 1:
            return {'key': generated_key}
        else: # cover 100
            self.abort(500, 'New key for user {} not generated'.format(self.uid))

    @require_admin
    def reset_registration(self, uid):
        new_registration_code = base64.urlsafe_b64encode(os.urandom(42))
        update = {
            'modified': datetime.datetime.utcnow(),
            'wechat': {
                'registration_code': new_registration_code
            }
        }
        result = self.storage.exec_op('PUT', _id=uid, payload=update)
        if result.modified_count == 1:
            return {'registration_code': new_registration_code}
        else: # cover 100
            self.abort(404, 'User {} not updated'.format(uid))

    def _get_user(self, _id):
        user = self.storage.get_container(_id)
        if user is not None:
            return user
        else: # cover 100
            self.abort(404, 'user {} not found'.format(_id))
