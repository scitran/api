# @author:  Gunnar Schaefer, Kevin S. Hahn

import copy
import json
import time
import random
import logging
import webapp2
import datetime
import requests
import jsonschema

from .util import log

# silence Requests library logging
logging.getLogger('requests').setLevel(logging.WARNING)


class RequestHandler(webapp2.RequestHandler):
    OAUTH_RETRY_LIMIT_SECONDS = 16  # Using exponential backoff and limits as recommended by Google
                            # https://developers.google.com/drive/web/handle-errors

    json_schema = None

    def resolve_token(self, access_token, request_start):
        current_retry_timeout = 1
        while (current_retry_timeout <= self.OAUTH_RETRY_LIMIT_SECONDS):
            r = requests.get(self.app.config['oauth2_id_endpoint'], headers={'Authorization': 'Bearer ' + access_token})

            #This condition results in a retry
            if r.status_code == 403:
                log.debug('OAuth provider reported 403 status, will retry. (Retry limit is %d)' % (r, current_retry_timeout))
                time.sleep(current_retry_timeout + random.random())
                current_retry_timeout *= 2

            #These conditions break out of the retry loop
            elif r.status_code == 200:
                identity = json.loads(r.content)
                self.uid = identity.get('email')
                if not self.uid:
                    self.abort(400, 'OAuth2 token resolution did not return email address')
                self.app.db.authtokens.replace_one({'_id': access_token}, {'uid': self.uid, 'timestamp': request_start}, upsert=True)
                log.debug('looked up remote token in %dms' % ((datetime.datetime.utcnow() - request_start).total_seconds() * 1000.))

                # Opportunistically set user's avatar based on their auth provider
                # TODO: after api starts reading toml config, switch on
                # auth.provider rather than manually comparing endpoint URL.
                if self.app.config['oauth2_id_endpoint'] == 'https://www.googleapis.com/plus/v1/people/me/openIdConnect':
                    avatar = identity.get('picture')
                    # NOTE: Google URLs have a size attached. This code removes that parameter.
                    # One could also set the size explicitly.
                    # from urllib import urlencode
                    # from urlparse import urlparse, urlunparse, parse_qs
                    # u = urlparse(avatar)
                    # query = parse_qs(u.query)
                    # query.pop('sz', None)
                    # u = u._replace(query=urlencode(query, True))
                    # avatar = urlunparse(u)
                    if avatar:
                        r = self.app.db.users.update_one({'_id': self.uid, 'avatar': {'$ne': avatar}}, {'$set':{'avatar': avatar, 'modified': request_start}})
                    break
            else:
                headers = {'WWW-Authenticate': 'Bearer realm="%s", error="invalid_token", error_description="Invalid OAuth2 token."' % self.app.config['site_id']}
                self.abort(401, 'invalid oauth2 token', headers=headers)
                break

    def __init__(self, request=None, response=None):
        self.initialize(request, response)
        self.debug = self.app.config['insecure']
        request_start = datetime.datetime.utcnow()

        # set uid, source_site, public_request, and superuser
        self.uid = None
        self.source_site = None
        drone_request = False

        access_token = self.request.headers.get('Authorization', None)
        drone_secret = self.request.headers.get('X-SciTran-Auth', None)

        # User (oAuth) authentication
        if access_token and self.app.config['oauth2_id_endpoint']:
            cached_token = self.app.db.authtokens.find_one({'_id': access_token})
            if cached_token:
                self.uid = cached_token['uid']
                log.debug('looked up cached token in %dms' % ((datetime.datetime.utcnow() - request_start).total_seconds() * 1000.))
            else:
                self.resolve_token(access_token, request_start)

        # 'Debug' (insecure) setting: allow request to act as requested user
        elif self.debug and self.request.GET.get('user'):
            self.uid = self.request.GET.get('user')

        # Drone shared secret authentication
        elif drone_secret is not None and self.request.user_agent.startswith('SciTran Drone '):
            if drone_secret != self.app.config['drone_secret']:
                self.abort(401, 'invalid drone secret')
            log.info('drone "' + self.request.user_agent.replace('SciTran Drone ', '') + '" request accepted')
            drone_request = True

        # Cross-site authentication
        elif self.request.user_agent.startswith('SciTran Instance '):
            if self.request.environ['SSL_CLIENT_VERIFY'] == 'SUCCESS':
                self.uid = self.request.headers.get('X-User')
                self.source_site = self.request.headers.get('X-Site')
                remote_instance = self.request.user_agent.replace('SciTran Instance', '').strip()
                if not self.app.db.sites.find_one({'_id': remote_instance}):
                    self.abort(402, remote_instance + ' is not an authorized remote instance')
            else:
                self.abort(401, 'no valid SSL client certificate')

        self.public_request = not drone_request and not self.uid

        if self.public_request or self.source_site:
            self.superuser_request = False
        elif drone_request:
            self.superuser_request = True
        else:
            user = self.app.db.users.find_one({'_id': self.uid}, ['root', 'wheel'])
            if not user:
                self.abort(403, 'user ' + self.uid + ' does not exist')
            self.superuser_request = user.get('root') and user.get('wheel')

    def dispatch(self):
        """dispatching and request forwarding"""
        target_site = self.request.GET.get('site', self.app.config['site_id'])
        if target_site == self.app.config['site_id']:
            log.debug('from %s %s %s %s %s' % (self.source_site, self.uid, self.request.method, self.request.path, str(self.request.GET.mixed())))
            return super(RequestHandler, self).dispatch()
        else:
            if not self.app.config['site_id']:
                self.abort(500, 'api site_id is not configured')
            if not self.app.config['ssl_cert']:
                self.abort(500, 'api ssl_cert is not configured')
            target = self.app.db.sites.find_one({'_id': target_site}, ['api_uri'])
            if not target:
                self.abort(402, 'remote host ' + target_site + ' is not an authorized remote')
            # adjust headers
            self.headers = self.request.headers
            self.headers['User-Agent'] = 'SciTran Instance ' + self.app.config['site_id']
            self.headers['X-User'] = self.uid
            self.headers['X-Site'] = self.app.config['site_id']
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
                    cert=self.app.config['ssl_cert'])
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
