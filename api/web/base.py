import base64
import datetime
import jsonschema
import os
import pymongo
import requests
import traceback
import webapp2

from .. import util
from .. import files
from .. import config
from ..types import Origin
from .. import validators
from ..auth.authproviders import AuthProvider, APIKeyAuthProvider
from ..auth import APIAuthProviderException, APIUnknownUserException, APIRefreshTokenException
from ..dao import APIConsistencyException, APIConflictException, APINotFoundException, APIPermissionException, APIValidationException
from ..dao.hierarchy import get_parent_tree
from ..web.request import log_access, AccessType


class RequestHandler(webapp2.RequestHandler):

    json_schema = None

    def __init__(self, request=None, response=None): # pylint: disable=super-init-not-called
        """Set uid, source_site, public_request, and superuser"""
        self.initialize(request, response)

        site_id = config.get_item('site', 'id')
        if site_id is None:
            self.abort(503, 'Database not initialized')

        self.source_site = None
        self.uid = None
        self.origin = None

        # If user is attempting to log in through `/login`, ignore Auth here:
        # In future updates, move login and logout handlers to class that overrides this init
        if self.request.path == '/api/login':
            self.source_site = site_id
            return

        try:
            # TODO: This should be taken out of base.RequestHandler so `handle_exception()`
            # can properly catch exceptions raised by this logic as well as uninteded exceptions
            # For now, wrap in a try/catch to prevent stack traces from getting to the client
            # For more info see scitran/core #733

            self.initialization_auth(site_id)

        except webapp2.HTTPException:
            raise
        except Exception: # pylint: disable=broad-except
            tb = traceback.format_exc()
            self.request.logger.error(tb)
            self.abort(500, 'Unexpected error.')



    def initialize(self, request, response):
        super(RequestHandler, self).initialize(request, response)
        request.logger.info("Initialized request")

    def initialization_auth(self, site_id):
        drone_request = False
        user_agent = self.request.headers.get('User-Agent', '')
        session_token = self.request.headers.get('Authorization', None)
        drone_secret = self.request.headers.get('X-SciTran-Auth', None)
        drone_method = self.request.headers.get('X-SciTran-Method', None)
        drone_name = self.request.headers.get('X-SciTran-Name', None)

        if session_token:
            if session_token.startswith('scitran-user '):
                # User (API key) authentication
                key = session_token.split()[1]
                self.uid = APIKeyAuthProvider.validate_user_api_key(key)
            elif session_token.startswith('scitran-drone '):
                # Drone (API key) authentication
                # When supported, remove custom headers and shared secret
                self.abort(401, 'Drone API keys are not yet supported')
            else:
                # User (oAuth) authentication
                self.uid = self.authenticate_user_token(session_token)



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
        # NOTE cross-site feature unused and planned for removal
        elif user_agent.startswith('SciTran Instance '): # pragma: no cover
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
            self.user_is_admin = False
        elif drone_request:
            self.superuser_request = True
            self.user_is_admin = True
        else:
            user = config.db.users.find_one({'_id': self.uid}, ['root', 'disabled'])
            if not user:
                self.abort(402, 'User {} will need to be added to the system before managing data.'.format(self.uid))
            if user.get('disabled', False) is True:
                self.abort(402, 'User {} is disabled.'.format(self.uid))
            if user.get('root'):
                self.user_is_admin = True
            else:
                self.user_is_admin = False
            if self.is_true('root'):
                if user.get('root'):
                    self.superuser_request = True
                else:
                    self.abort(403, 'user ' + self.uid + ' is not authorized to make superuser requests')
            else:
                self.superuser_request = False

        self.origin = None
        self.set_origin(drone_request)

    def authenticate_user_token(self, session_token):
        """
        AuthN for user accounts. Calls self.abort on failure.

        Returns the user's UID.
        """

        uid = None
        timestamp = datetime.datetime.utcnow()
        cached_token = config.db.authtokens.find_one({'_id': session_token})

        if cached_token:
            self.request.logger.debug('looked up cached token in %dms', ((datetime.datetime.utcnow() - timestamp).total_seconds() * 1000.))

            # Check if token is expired
            if cached_token.get('expires') and timestamp > cached_token['expires']:

                # look to see if the user has a stored refresh token:
                unverified_uid = cached_token['uid']
                auth_type = cached_token['auth_type']
                refresh_token = config.db.refreshtokens.find_one({'uid': unverified_uid, 'auth_type': cached_token['auth_type']})
                if refresh_token:
                    # Attempt to refresh the token, update db

                    try:
                        auth_provider = AuthProvider.factory(auth_type)
                    except NotImplementedError as e:
                        self.abort(401, str(e))

                    try:
                        updated_token_info = auth_provider.refresh_token(refresh_token['token'])
                    except APIAuthProviderException as e:

                        # Remove the bad refresh token and session token:
                        config.db.refreshtokens.delete_one({'_id': refresh_token['_id']})
                        config.db.authtokens.delete_one({'_id': cached_token['_id']})

                        # TODO: Rework auth so it's not tied to init, then:
                        #   - Raise a refresh token exception specifically in this situation
                        #   - Alerts clients they may need to re-ask for `offline` permission
                        # Until then, the key `invalid_refresh_token` alerts the client
                        self.abort(401, 'invalid_refresh_token')

                    config.db.authtokens.update_one({'_id': cached_token['_id']}, {'$set': updated_token_info})

                else:
                    # Token expired and no refresh token, remove and deny request
                    config.db.authtokens.delete_one({'_id': cached_token['_id']})
                    self.abort(401, 'invalid_refresh_token')

            uid = cached_token['uid']
        else:
            self.abort(401, 'Invalid session token')

        return uid


    @log_access(AccessType.user_login)
    def log_in(self):
        """
        Return succcess boolean if user successfully authenticates.

        Used for access logging.
        Not required to use system as logged in user.
        """

        payload = self.request.json_body
        if 'code' not in payload or 'auth_type' not in payload:
            self.abort(400, 'Auth code and type required for login')

        auth_type = payload['auth_type']
        try:
            auth_provider = AuthProvider.factory(auth_type)
        except NotImplementedError as e:
            self.abort(400, str(e))

        registration_code = payload.get('registration_code')
        token_entry = auth_provider.validate_code(payload['code'], registration_code=registration_code)
        timestamp = datetime.datetime.utcnow()

        self.uid = token_entry['uid']

        # If this is the first time they've logged in, record that
        config.db.users.update_one({'_id': self.uid, 'firstlogin': None}, {'$set': {'firstlogin': timestamp}})
        # Unconditionally set their most recent login time
        config.db.users.update_one({'_id': self.uid}, {'$set': {'lastlogin': timestamp}})

        session_token = base64.urlsafe_b64encode(os.urandom(42))
        token_entry['_id'] = session_token
        token_entry['timestamp'] = timestamp

        config.db.authtokens.insert_one(token_entry)

        # Set origin now that the uid is known
        self.set_origin(False)

        return {'token': session_token}


    @log_access(AccessType.user_logout)
    def log_out(self):
        """
        Remove all cached auth tokens associated with caller's uid.
        """

        token = self.request.headers.get('Authorization', None)
        if not token:
            self.abort(401, 'User not logged in.')
        result = config.db.authtokens.delete_one({'_id': token})
        return {'tokens_removed': result.deleted_count}


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
                        'last_seen': datetime.datetime.utcnow(),
                        'method': self.origin['method'],
                        'name': self.origin['name'],
                        'errors': [] # Reset errors list if device checks in
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

        custom_errors = None
        if isinstance(exception, webapp2.HTTPException):
            code = exception.code
        elif isinstance(exception, validators.InputValidationException):
            code = 400
            self.request.logger.warning(str(exception))
        elif isinstance(exception, APIAuthProviderException):
            code = 401
        elif isinstance(exception, APIRefreshTokenException):
            code = 401
            custom_errors = exception.errors
        elif isinstance(exception, APIUnknownUserException):
            code = 402
        elif isinstance(exception, APIConsistencyException):
            code = 400
        elif isinstance(exception, APIPermissionException):
            code = 403
        elif isinstance(exception, APINotFoundException):
            code = 404
        elif isinstance(exception, APIConflictException):
            code = 409
        elif isinstance(exception, APIValidationException):
            code = 422
            custom_errors = exception.errors
        elif isinstance(exception, files.FileStoreException):
            code = 400
        else:
            code = 500

        if code == 500:
            tb = traceback.format_exc()
            self.request.logger.error(tb)

        util.send_json_http_exception(self.response, str(exception), code, custom=custom_errors)

    def log_user_access(self, access_type, cont_name=None, cont_id=None):

        if not config.get_item('core', 'access_log_enabled'):
            return

        if not isinstance(access_type, AccessType):
            raise Exception('Unknown access type.')

        log_map = {
            'access_type':      access_type.value,
            'request_method':   self.request.method,
            'request_path':     self.request.path,
            'origin':           self.origin,
            'timestamp':        datetime.datetime.utcnow()
        }

        if access_type not in [AccessType.user_login, AccessType.user_logout]:

            if cont_name is None or cont_id is None:
                raise Exception('Container information not available.')

            # Create a context tree for the container
            context = {}

            if cont_name in ['collection', 'collections']:
                context['collection'] = {'id': cont_id}
            else:
                tree = get_parent_tree(cont_name, cont_id)

                for k,v in tree.iteritems():
                    context[k] = {'id': str(v['_id']), 'label': v.get('label')}
                    if k == 'group':
                        context[k]['label'] = v.get('name')
                    if k == 'subject':
                        context[k]['label'] = v.get('code')
            log_map['context'] = context

        if access_type is AccessType.download_file and self.get_param('ticket'):
            # If this is a ticket download, log only once per ticket
            ticket_id = self.get_param('ticket')
            log_map['context']['ticket_id'] = ticket_id
            try:
                config.log_db.access_log.update(
                    {'context.ticket_id': ticket_id},
                    {'$setOnInsert': log_map},
                    upsert=True
                )
            except Exception as e:  # pylint: disable=broad-except
                config.log.exception(e)
                self.abort(500, 'Unable to log access.')

        else:
            try:
                config.log_db.access_log.insert_one(log_map)
            except Exception as e:  # pylint: disable=broad-except
                config.log.exception(e)
                self.abort(500, 'Unable to log access.')


    def dispatch(self):
        """dispatching and request forwarding"""

        site_id = config.get_item('site', 'id')
        target_site = self.get_param('site', site_id)
        if target_site == site_id:
            self.request.logger.debug('from %s %s %s %s %s', self.source_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed()))
            return super(RequestHandler, self).dispatch()
        # NOTE cross-site feature unused and planned for removal
        else: # pragma: no cover
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
            self.request.logger.debug(' for %s %s %s %s %s', target_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed()))
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
        self.request.logger.warning(str(self.uid) + ' ' + str(code) + ' ' + str(detail))
        webapp2.abort(code, detail=detail, **kwargs)
