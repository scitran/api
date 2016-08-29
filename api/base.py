import datetime
import json
import jsonschema
import pymongo
import requests
import traceback
import urllib
import urlparse
import webapp2

from . import util
from . import files
from . import config
from .types import Origin
from . import validators
from .dao import APIConsistencyException, APIConflictException, APINotFoundException

log = config.log

class RequestHandler(webapp2.RequestHandler):

    json_schema = None

    def __init__(self, request=None, response=None): # pylint: disable=super-init-not-called
        self.initialize(request, response)
        self.debug = config.get_item('core', 'insecure')

        # set uid, source_site, public_request, and superuser
        self.uid = None
        self.source_site = None
        drone_request = False

        user_agent = self.request.headers.get('User-Agent', '')
        access_token = self.request.headers.get('Authorization', None)
        drone_secret = self.request.headers.get('X-SciTran-Auth', None)
        drone_method = self.request.headers.get('X-SciTran-Method', None)
        drone_name = self.request.headers.get('X-SciTran-Name', None)

        site_id = config.get_item('site', 'id')
        if site_id is None:
            self.abort(503, 'Database not initialized')

        if access_token:
            if access_token.startswith('scitran-user '):
                # User (API key) authentication
                key = access_token.split()[1]
                self.uid = self.authenticate_user_api_key(key)
            elif access_token.startswith('scitran-drone '):
                # Drone (API key) authentication
                # When supported, remove custom headers and shared secret
                self.abort(401, 'Drone API keys are not yet supported')
            else:
                # User (oAuth) authentication
                self.uid = self.authenticate_user(access_token)

        # 'Debug' (insecure) setting: allow request to act as requested user
        elif self.debug and self.get_param('user'):
            self.uid = self.get_param('user')

        # Drone shared secret authentication
        elif drone_secret is not None:
            if drone_method is None or drone_name is None:
                self.abort(400, 'X-SciTran-Method or X-SciTran-Name header missing')
            if config.get_item('core', 'drone_secret') is None:
                self.abort(401, 'drone secret not configured')
            if drone_secret != config.get_item('core', 'drone_secret'):
                self.abort(401, 'invalid drone secret')
            drone_request = True

        # Cross-site authentication
        elif user_agent.startswith('SciTran Instance '):
            if self.request.environ['SSL_CLIENT_VERIFY'] == 'SUCCESS':
                self.uid = self.request.headers.get('X-User')
                self.source_site = self.request.headers.get('X-Site')
                remote_instance = user_agent.replace('SciTran Instance', '').strip()
                if not config.db.sites.find_one({'_id': remote_instance}):
                    self.abort(402, remote_instance + ' is not an authorized remote instance')
            else:
                self.abort(401, 'no valid SSL client certificate')

        self.user_site = self.source_site or site_id
        self.public_request = not drone_request and not self.uid

        if self.public_request or self.source_site:
            self.superuser_request = False
        elif drone_request:
            self.superuser_request = True
        else:
            user = config.db.users.find_one({'_id': self.uid}, ['root', 'disabled'])
            if not user:
                self.abort(402, 'user ' + self.uid + ' does not exist')
            if user.get('disabled', False) is True:
                self.abort(402, 'user account ' + self.uid + ' is disabled')
            if self.is_true('root'):
                if user.get('root'):
                    self.superuser_request = True
                else:
                    self.abort(403, 'user ' + self.uid + ' is not authorized to make superuser requests')
            else:
                self.superuser_request = False

        self.set_origin(drone_request)

    def authenticate_user_api_key(self, key):
        """
        AuthN for user accounts via api key. Calls self.abort on failure.

        Returns the user's UID.
        """

        timestamp = datetime.datetime.utcnow()
        user = config.db.users.find_one_and_update({'api_key.key': key}, {'$set': {'api_key.last_used': timestamp}}, ['_id'])
        if user:
            return user['_id']
        else:
            self.abort(401, 'Invalid scitran-user API key')


    def authenticate_user(self, access_token):
        """
        AuthN for user accounts. Calls self.abort on failure.

        Returns the user's UID.
        """

        uid = None
        timestamp = datetime.datetime.utcnow()
        cached_token = config.db.authtokens.find_one({'_id': access_token})

        if cached_token:
            uid = cached_token['uid']
            log.debug('looked up cached token in %dms', ((datetime.datetime.utcnow() - timestamp).total_seconds() * 1000.))
        else:
            uid = self.validate_oauth_token(access_token, timestamp)
            log.debug('looked up remote token in %dms', ((datetime.datetime.utcnow() - timestamp).total_seconds() * 1000.))

            # Cache the token for future requests
            config.db.authtokens.replace_one({'_id': access_token}, {'uid': uid, 'timestamp': timestamp}, upsert=True)

        return uid

    def validate_oauth_token(self, access_token, timestamp):
        """
        Validates a token assertion against the configured ID endpoint. Calls self.abort on failure.

        Returns the user's UID.
        """

        r = requests.get(config.get_item('auth', 'id_endpoint'), headers={'Authorization': 'Bearer ' + access_token})

        if not r.ok:
            # Oauth authN failed; for now assume it was an invalid token. Could be more accurate in the future.
            err_msg = 'Invalid OAuth2 token.'
            site_id = config.get_item('site', 'id')
            headers = {'WWW-Authenticate': 'Bearer realm="{}", error="invalid_token", error_description="{}"'.format(site_id, err_msg)}
            log.warn('{} Request headers: {}'.format(err_msg, str(self.request.headers.items())))
            self.abort(401, err_msg, headers=headers)

        identity = json.loads(r.content)
        uid = identity.get('email')

        if not uid:
            self.abort(400, 'OAuth2 token resolution did not return email address')

        # If this is the first time they've logged in, record that
        config.db.users.update_one({'_id': self.uid, 'firstlogin': None}, {'$set': {'firstlogin': timestamp}})

        # Unconditionally set their most recent login time
        config.db.users.update_one({'_id': self.uid}, {'$set': {'lastlogin': timestamp}})

        # Set user's auth provider avatar
        # TODO: switch on auth.provider rather than manually comparing endpoint URL.
        if config.get_item('auth', 'id_endpoint') == 'https://www.googleapis.com/plus/v1/people/me/openIdConnect':
            # A google-specific avatar URL is provided in the identity return.
            provider_avatar = identity.get('picture', '')

            # Remove attached size param from URL.
            u = urlparse.urlparse(provider_avatar)
            query = urlparse.parse_qs(u.query)
            query.pop('sz', None)
            u = u._replace(query=urllib.urlencode(query, True))
            provider_avatar = urlparse.urlunparse(u)
            # Update the user's provider avatar if it has changed.
            config.db.users.update_one({'_id': uid, 'avatars.provider': {'$ne': provider_avatar}}, {'$set':{'avatars.provider': provider_avatar, 'modified': timestamp}})

            # If the user has no avatar set, mark their provider_avatar as their chosen avatar.
            config.db.users.update_one({'_id': uid, 'avatar': {'$exists': False}}, {'$set':{'avatar': provider_avatar, 'modified': timestamp}})

        # Look to see if user has a Gravatar
        gravatar = util.resolve_gravatar(uid)
        if gravatar is not None:
            # Update the user's gravatar if it has changed.
            config.db.users.update_one({'_id': uid, 'avatars.gravatar': {'$ne': gravatar}}, {'$set':{'avatars.gravatar': gravatar, 'modified': timestamp}})

        return uid

    def set_origin(self, drone_request):
        """
        Add an origin to the request object. Used later in request handler logic.

        Pretty clear duplication of logic with superuser_request / drone_request;
        this map serves a different purpose, and specifically matches the desired file-origin map.
        Might be a good future project to remove one or the other.
        """

        if self.uid is not None:
            self.origin = {
                'type': str(Origin.user),
                'id': self.uid
            }
        elif drone_request:

            method = self.request.headers.get('X-SciTran-Method')
            name = self.request.headers.get('X-SciTran-Name')

            self.origin = {
                'id': (method + '_' + name).replace(' ', '_'),
                'type': str(Origin.device),
                'method': method,
                'name': name
            }

            # Upsert device record, with last-contacted time.
            # In the future, consider merging any keys into self.origin?
            config.db['devices'].find_one_and_update({
                    '_id': self.origin['id']
                }, {
                    '$set': {
                        '_id': self.origin['id'],
                        'last-seen': datetime.datetime.utcnow(),
                        'method': self.origin['method'],
                        'name': self.origin['name']
                    }
                },
                upsert=True,
                return_document=pymongo.collection.ReturnDocument.AFTER
            )

            # Bit hackish - detect from route if a job is the origin, and if so what job ID.
            # Could be removed if routes get reorganized. POST /api/jobs/id/result, maybe?
            is_job_upload = self.request.path.startswith('/api/engine')
            job_id        = self.request.GET.get('job')

            # This runs after the standard drone-request upsert above so that we can still update the last-seen timestamp.
            if is_job_upload and job_id is not None:
                self.origin = {
                    'type': str(Origin.job),
                    'id': job_id
                }
        else:
            self.origin = {
                'type': str(Origin.unknown),
                'id': None
            }


    def is_true(self, param):
        return self.request.GET.get(param, '').lower() in ('1', 'true')

    def get_param(self, param, default=None):
        return self.request.GET.get(param, default)

    def handle_exception(self, exception, debug):
        """
        Send JSON response for exception

        For HTTP and other known exceptions, use its error code
        For all others use a generic 500 error code and log the stack trace
        """
        if isinstance(exception, webapp2.HTTPException):
            code = exception.code
        elif isinstance(exception, validators.InputValidationException):
            code = 422
            log.warn(str(exception))
        elif isinstance(exception, APIConsistencyException):
            code = 400
        elif isinstance(exception, APINotFoundException):
            code = 404
        elif isinstance(exception, APIConflictException):
            code = 409
        elif isinstance(exception, files.FileStoreException):
            code = 400
        else:
            code = 500

        if code == 500:
            tb = traceback.format_exc()
            log.error(tb)

        util.send_json_http_exception(self.response, str(exception), code)

    def dispatch(self):
        """dispatching and request forwarding"""

        site_id = config.get_item('site', 'id')
        target_site = self.get_param('site', site_id)
        if target_site == site_id:
            log.debug('from %s %s %s %s %s', self.source_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed()))
            return super(RequestHandler, self).dispatch()
        else:
            if not site_id:
                self.abort(500, 'api site.id is not configured')
            if not config.get_item('site', 'ssl_cert'):
                self.abort(500, 'api ssl_cert is not configured')
            target = config.db.sites.find_one({'_id': target_site}, ['api_uri'])
            if not target:
                self.abort(402, 'remote host ' + target_site + ' is not an authorized remote')
            # adjust headers
            headers = self.request.headers
            headers['User-Agent'] = 'SciTran Instance ' + site_id
            headers['X-User'] = self.uid
            headers['X-Site'] = site_id
            headers['Content-Length'] = len(self.request.body)
            del headers['Host']
            if 'Authorization' in headers: del headers['Authorization']
            # adjust params
            params = self.request.GET.mixed()
            if 'user' in params: del params['user']
            del params['site']
            log.debug(' for %s %s %s %s %s', target_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed()))
            target_uri = target['api_uri'] + self.request.path.split('/api')[1]
            r = requests.request(
                    self.request.method,
                    target_uri,
                    stream=True,
                    params=params,
                    data=self.request.body_file,
                    headers=headers,
                    cert=config.get_item('site', 'ssl_cert'))
            if r.status_code != 200:
                self.abort(r.status_code, 'InterNIMS p2p err: ' + r.reason)
            self.response.app_iter = r.iter_content(2**20)
            for header in ['Content-' + h for h in 'Length', 'Type', 'Disposition']:
                if header in r.headers:
                    self.response.headers[header] = r.headers[header]

    def abort(self, code, detail=None, **kwargs):
        if isinstance(detail, jsonschema.ValidationError):
            detail = {
                'relative_path': list(detail.relative_path),
                'instance': detail.instance,
                'validator': detail.validator,
                'validator_value': detail.validator_value,
            }
        log.warning(str(self.uid) + ' ' + str(code) + ' ' + str(detail))
        webapp2.abort(code, detail=detail, **kwargs)
