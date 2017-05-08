import datetime
import requests
import json
import urllib
import urlparse

from . import APIAuthProviderException, APIUnknownUserException, APIRefreshTokenException
from .. import config, util
from ..dao import dbutil

log = config.log

class AuthProvider(object):
    """
    This class provides access to mongodb collection elements (called containers).
    It is used by ContainerHandler istances for get, create, update and delete operations on containers.
    Examples: projects, sessions, acquisitions and collections
    """

    def __init__(self, auth_type, set_config=True):
        self.auth_type = auth_type
        if set_config:
            try:
                self.config = config.get_auth(auth_type)
            except KeyError:
                raise NotImplementedError('Auth type {} is not supported by this instance'.format(auth_type))

    @staticmethod
    def factory(auth_type):
        """
        Factory method to aid in the creation of an AuthProvider instance
        when auth_type is dynamic.
        """
        if auth_type in AuthProviders:
            provider_class = AuthProviders[auth_type]
            return provider_class()
        else:
            raise NotImplementedError('Auth type {} is not supported'.format(auth_type))

    def validate_code(self, code, **kwargs):
        raise NotImplementedError

    def ensure_user_exists(self, uid):
        user = config.db.users.find_one({'_id': uid})
        if not user:
            raise APIUnknownUserException('User {} will need to be added to the system before managing data.'.format(uid))
        if user.get('disabled', False) is True:
            raise APIUnknownUserException('User {} is disabled.'.format(uid))

    def set_user_gravatar(self, uid, email):
        """
        Looks for user gravatar via email. If a gravatar is found, adds to avatar map.
        If the user has not yet set an avatar (first time logging in), set the default
        avatar to the gravatar image.
        """
        if email and uid:
            gravatar = util.resolve_gravatar(email)
            if gravatar is not None:
                timestamp = datetime.datetime.utcnow()
                # Update the user's gravatar if it has changed.
                config.db.users.update_one({'_id': uid, 'avatars.gravatar': {'$ne': gravatar}},{'$set':{'avatars.gravatar': gravatar,'modified': timestamp}})
                # If the user has no avatar set, use gravar
                config.db.users.update_one({'_id': uid, 'avatar': {'$exists': False}}, {'$set':{'avatar': gravatar, 'modified': timestamp}})

    def set_refresh_token_if_exists(self, uid, refresh_token):
        # Also check to make sure if refresh token is missing, that the user
        # has a refresh token on their user doc. If not, alert the client.
        query = {'uid': uid, 'auth_type': self.auth_type}
        if not refresh_token:
            token = config.db.refreshtokens.find_one(query)
            if not token:
                # user does not have refresh token, alert the client
                raise APIRefreshTokenException('invalid_refresh_token')
            else:
                # user does have a previously saved refresh token, move on
                return

        refresh_doc = {
            'token': refresh_token,
            'auth_type': self.auth_type,
            'uid': uid
        }
        dbutil.fault_tolerant_replace_one('refreshtokens', query, refresh_doc, upsert=True)

class JWTAuthProvider(AuthProvider):

    def __init__(self):
        super(JWTAuthProvider,self).__init__('ldap')

    def validate_code(self, code, **kwargs):
        uid = self.validate_user(code)
        return {
            'access_token': code,
            'uid': uid,
            'auth_type': self.auth_type,
            'expires': datetime.datetime.utcnow() + datetime.timedelta(days=14)
        }

    def validate_user(self, token):
        r = requests.post(self.config['verify_endpoint'], data={'token': token}, verify=self.config.get('check_ssl', True))
        if not r.ok:
            raise APIAuthProviderException('User token not valid')
        uid = json.loads(r.content).get('mail')
        if not uid:
            raise APIAuthProviderException('Auth provider did not provide user email')

        self.ensure_user_exists(uid)
        self.set_user_gravatar(uid, uid)

        return uid

class GoogleOAuthProvider(AuthProvider):

    def __init__(self):
        super(GoogleOAuthProvider, self).__init__('google')

    def validate_code(self, code, **kwargs):
        payload = {
            'client_id':        self.config['client_id'],
            'client_secret':    self.config['client_secret'],
            'code':             code,
            'grant_type':       'authorization_code',
            'redirect_uri':     config.get_item('site', 'redirect_url')
        }

        r = requests.post(self.config['token_endpoint'], data=payload)
        if not r.ok:
            raise APIAuthProviderException('User code not valid')

        response = json.loads(r.content)
        token = response['access_token']

        uid = self.validate_user(token)
        self.set_refresh_token_if_exists(uid, response.get('refresh_token'))

        return {
            'access_token': token,
            'uid': uid,
            'auth_type': self.auth_type,
            'expires': datetime.datetime.utcnow() + datetime.timedelta(seconds=response['expires_in'])
        }

    def refresh_token(self, token):
        payload = {
            'client_id':        self.config['client_id'],
            'client_secret':    self.config['client_secret'],
            'refresh_token':    token,
            'grant_type':       'refresh_token',
        }
        r = requests.post(self.config['refresh_endpoint'], data=payload)
        if not r.ok:
            raise APIAuthProviderException('Unable to refresh token.')

        response = json.loads(r.content)
        return {
            'access_token': response['access_token'],
            'expires': datetime.datetime.utcnow() + datetime.timedelta(seconds=response['expires_in'])
        }

    def validate_user(self, token):
        r = requests.get(self.config['id_endpoint'], headers={'Authorization': 'Bearer ' + token})
        if not r.ok:
            raise APIAuthProviderException('User token not valid')
        identity = json.loads(r.content)
        uid = identity.get('email')
        if not uid:
            raise APIAuthProviderException('Auth provider did not provide user email')

        self.ensure_user_exists(uid)
        self.set_user_gravatar(uid, uid)
        self.set_user_avatar(uid, identity)

        return uid

    def set_user_avatar(self, uid, identity):
        # A google-specific avatar URL is provided in the identity return.
        provider_avatar = identity.get('picture', '')

        # Remove attached size param from URL.
        u = urlparse.urlparse(provider_avatar)
        query = urlparse.parse_qs(u.query)
        query.pop('sz', None)
        u = u._replace(query=urllib.urlencode(query, True))
        provider_avatar = urlparse.urlunparse(u)

        timestamp = datetime.datetime.utcnow()
        # Update the user's provider avatar if it has changed.
        config.db.users.update_one({'_id': uid, 'avatars.provider': {'$ne': provider_avatar}}, {'$set':{'avatars.provider': provider_avatar, 'modified': timestamp}})
        # If the user has no avatar set, mark their provider_avatar as their chosen avatar.
        config.db.users.update_one({'_id': uid, 'avatar': {'$exists': False}}, {'$set':{'avatar': provider_avatar, 'modified': timestamp}})

class WechatOAuthProvider(AuthProvider):

    def __init__(self):
        super(WechatOAuthProvider,self).__init__('wechat')

    def validate_code(self, code, **kwargs):
        payload = {
            'appid':        self.config['client_id'],
            'secret':       self.config['client_secret'],
            'code':         code,
            'grant_type':   'authorization_code'
        }
        r = requests.post(self.config['token_endpoint'], params=payload)
        if not r.ok:
            raise APIAuthProviderException('User code not valid')

        response = json.loads(r.content)
        openid = response.get('openid')
        if not openid:
            raise APIAuthProviderException('Open ID not returned with successful auth.')

        registration_code = kwargs.get('registration_code')
        uid = self.validate_user(openid, registration_code=registration_code)
        self.set_refresh_token_if_exists(uid, response.get('refresh_token'))

        return {
            'access_token': response['access_token'],
            'uid': uid,
            'auth_type': self.auth_type,
            'expires': datetime.datetime.utcnow() + datetime.timedelta(seconds=response['expires_in'])
        }

    def refresh_token(self, token):
        payload = {
            'appid':            self.config['client_id'],
            'refresh_token':    token,
            'grant_type':       'refresh_token'
        }
        r = requests.post(self.config['refresh_endpoint'], params=payload)
        if not r.ok:
            raise APIAuthProviderException('Unable to refresh token.')

        response = json.loads(r.content)
        return {
            'access_token': response['access_token'],
            'expires': datetime.datetime.utcnow() + datetime.timedelta(seconds=response['expires_in'])
        }

    def validate_user(self, openid, registration_code=None):
        if registration_code:
            user = config.db.users.find_one({'wechat.registration_code': registration_code})
            if user is None:
                raise APIUnknownUserException('Invalid or expired registration link.')

            # Check to make sure there is not already a user with this wechat openid:
            conflicts = config.db.users.find({'wechat.openid': openid})
            if conflicts.count() > 0:
                # For now, throw the error in access log so the site admin can find it
                log_map = {
                    'access_type':      'user_conflict',
                    'timestamp':        datetime.datetime.utcnow(),
                    'conflicts':        [c['_id'] for c in conflicts],
                    'attempted_user':   user['_id']
                }
                config.log_db.access_log.insert_one(log_map)
                raise APIUnknownUserException('Another user is already registered with this Wechat OpenID.')
            update = {
                '$set': {
                    'wechat.openid': openid
                },
                '$unset': {
                    'wechat.registration_code':''
                }
            }
            config.db.users.update_one({'_id': user['_id']}, update)
        else:
            user = config.db.users.find_one({'wechat.openid': openid})
        if not user:
            raise APIUnknownUserException('No user associated with this WeChat OpenID. Please use a valid registration link upon first sign in.')
        if user.get('disabled', False) is True:
            raise APIUnknownUserException('User {} is disabled.'.format(user['_id']))

        return user['_id']

    def set_user_avatar(self, uid, identity):
        pass

class APIKeyAuthProvider(AuthProvider):
    """
    Uses an API key for authentication.

    Note: This auth provider is mainly used for testing. A user
    can access the API directly by placing their API key in the
    Authorization header. There is no need for them to exchange
    the key for a session token in normal usecases.

    The static method is used by the base RequestHandler to
    verify the API key and attach it to a user.
    """

    def __init__(self):
        """
        Does not need to be supported in config.
        """
        super(APIKeyAuthProvider, self).__init__('api-key', set_config=False)

    @staticmethod
    def _preprocess_key(key):
        """
        Convention for API keys is that they can have arbitrary information, separated by a :,
        before the actual key. Generally, this will have a connection string in it.
        Strip this preamble, if any, before processing the key.
        """

        return key.split(":")[-1] # Get the last segment of the string after any : separators

    def validate_code(self, code, **kwargs):
        code = APIKeyAuthProvider._preprocess_key(code)

        uid = self.validate_user_api_key(code)
        return {
            'access_token': code,
            'uid': uid,
            'auth_type': self.auth_type,
            'expires': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }

    @staticmethod
    def validate_user_api_key(key):
        """
        AuthN for user accounts via api key.

        401s via APIAuthProviderException on failure.
        """
        key = APIKeyAuthProvider._preprocess_key(key)

        timestamp = datetime.datetime.utcnow()
        user = config.db.users.find_one_and_update({'api_key.key': key}, {'$set': {'api_key.last_used': timestamp}}, ['_id'])
        if user:
            return user['_id']
        else:
            raise APIAuthProviderException('Invalid scitran-user API key')


AuthProviders = {
    'google'    : GoogleOAuthProvider,
    'ldap'      : JWTAuthProvider,
    'wechat'    : WechatOAuthProvider,
    'api-key'   : APIKeyAuthProvider
}
