import copy
import json
import urllib
import webapp2
import datetime
import requests
import urlparse
import jsonschema

from auth.provider import AuthProviders

from . import config

log = config.log


class RequestHandler(webapp2.RequestHandler):

    json_schema = None

    def __init__(self, request=None, response=None):
        self.initialize(request, response)
        self.debug = config.get_item('core', 'insecure')
        request_start = datetime.datetime.utcnow()
        provider_avatar = None

        # set uid, source_site, public_request, and superuser
        self.uid = None
        self.source_site = None
        drone_request = False

        user_agent = self.request.headers.get('User-Agent', '')
        access_token = self.request.headers.get('Authorization', None)
        access_provider = self.request.headers.get('Authorization-Provider', 'google')
        drone_secret = self.request.headers.get('X-SciTran-Auth', None)

        site_id = config.get_item('site', 'id')
        if site_id is None:
            self.abort(503, 'Database not initialized')

        # User (oAuth) authentication
        if access_token:
            cached_token = config.db.authtokens.find_one({'_id': access_token})
            if cached_token:
                self.uid = cached_token['uid']
                log.debug('looked up cached token in %dms' % ((datetime.datetime.utcnow() - request_start).total_seconds() * 1000.))
            else:
                # Fallback for Google oAuth provider
                if access_provider not in AuthProviders:
                    access_provider = 'google'

                provider = AuthProviders[access_provider]
                identity = provider(access_token)
                if not identity:
                    headers = {'WWW-Authenticate': 'Bearer realm="{}", error="invalid_token", error_description="Invalid OAuth2 token."'.format(site_id)}
                    self.abort(401, 'invalid oauth2 token', headers=headers)

                if not identity.get('uid'):
                    self.abort(400, 'OAuth2 token resolution did not return user identification')

                self.uid = identity.get('uid')

                config.db.authtokens.replace_one({'_id': access_token}, {'uid': self.uid, 'timestamp': request_start}, upsert=True)
                config.db.users.update_one({'_id': self.uid, 'firstlogin': None}, {'$set': {'firstlogin': request_start}})
                config.db.users.update_one({'_id': self.uid}, {'$set': {'lastlogin': request_start}})

                log.debug('looked up remote token in %dms' % ((datetime.datetime.utcnow() - request_start).total_seconds() * 1000.))

                # Set user's auth provider avatar
                if 'avatar' in identity:
                    provider_avatar = identity.get('avatar')

        # 'Debug' (insecure) setting: allow request to act as requested user
        elif self.debug and self.get_param('user'):
            self.uid = self.get_param('user')

        # Drone shared secret authentication
        elif drone_secret is not None and user_agent.startswith('SciTran Drone '):
            if config.get_item('core', 'drone_secret') is None:
                self.abort(401, 'drone secret not configured')
            if drone_secret != config.get_item('core', 'drone_secret'):
                self.abort(401, 'invalid drone secret')
            log.info('drone "' + user_agent.replace('SciTran Drone ', '') + '" request accepted')
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
            user = config.db.users.find_one({'_id': self.uid}, ['root'])
            if not user:
                self.abort(403, 'user ' + self.uid + ' does not exist')
            if provider_avatar:
                config.db.users.update_one({'_id': self.uid, 'avatar': None}, {'$set':{'avatar': provider_avatar, 'modified': request_start}})
                config.db.users.update_one({'_id': self.uid, 'avatars.provider': {'$ne': provider_avatar}}, {'$set':{'avatars.provider': provider_avatar, 'modified': request_start}})
            if self.is_true('root'):
                if user.get('root'):
                    self.superuser_request = True
                else:
                    self.abort(403, 'user ' + self.uid + ' is not authorized to make superuser requests')
            else:
                self.superuser_request = False

    def is_true(self, param):
        return self.request.GET.get(param, '').lower() in ('1', 'true')

    def get_param(self, param, default=None):
        return self.request.GET.get(param, default)

    def dispatch(self):
        """dispatching and request forwarding"""
        site_id = config.get_item('site', 'id')
        target_site = self.get_param('site', site_id)
        if target_site == site_id:
            log.debug('from %s %s %s %s %s' % (self.source_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed())))
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
            self.headers = self.request.headers
            self.headers['User-Agent'] = 'SciTran Instance ' + site_id
            self.headers['X-User'] = self.uid
            self.headers['X-Site'] = site_id
            self.headers['Content-Length'] = len(self.request.body)
            del self.headers['Host']
            if 'Authorization' in self.headers: del self.headers['Authorization']
            # adjust params
            self.params = self.request.GET.mixed()
            if 'user' in self.params: del self.params['user']
            del self.params['site']
            log.debug(' for %s %s %s %s %s' % (target_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed())))
            target_uri = target['api_uri'] + self.request.path.split('/api')[1]
            r = requests.request(
                    self.request.method,
                    target_uri,
                    stream=True,
                    params=self.params,
                    data=self.request.body_file,
                    headers=self.headers,
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
        log.warning(str(code) + ' ' + str(detail))
        json_body = {
                'uid': self.uid,
                'code': code,
                'detail': detail,
                }
        webapp2.abort(code, json_body=json_body, **kwargs)

    def schema(self, updates={}):
        json_schema = copy.deepcopy(self.json_schema)
        json_schema['properties'].update(updates)
        return json_schema
