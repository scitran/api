# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
log = logging.getLogger('scitran.api')
logging.getLogger('requests').setLevel(logging.WARNING) # silence Requests library logging

import copy
import json
import hashlib
import webapp2
import datetime
import requests


class RequestHandler(webapp2.RequestHandler):

    json_schema = None

    def __init__(self, request=None, response=None):
        self.initialize(request, response)
        self.debug = self.app.config['insecure']

        # set uid, source_site, public_request, and superuser
        self.uid = None
        self.source_site = None
        self.drone_request = False
        identity = {}
        access_token = self.request.headers.get('Authorization', None)
        if access_token and self.app.config['oauth2_id_endpoint']:
            token_request_time = datetime.datetime.now()
            cached_token = self.app.db.tokens.find_one({'_id': access_token})
            if cached_token:
                self.uid = cached_token['uid']
                log.debug('looked up cached token in %dms' % ((datetime.datetime.now() - token_request_time).total_seconds() * 1000.))
            else:
                r = requests.get(self.app.config['oauth2_id_endpoint'], headers={'Authorization': 'Bearer ' + access_token})
                if r.status_code == 200:
                    identity = json.loads(r.content)
                    self.uid = identity['email']
                    self.app.db.tokens.save({'_id': access_token, 'uid': self.uid, 'timestamp': datetime.datetime.utcnow()})
                    log.debug('looked up remote token in %dms' % ((datetime.datetime.now() - token_request_time).total_seconds() * 1000.))
                else:
                    headers = {'WWW-Authenticate': 'Bearer realm="%s", error="invalid_token", error_description="Invalid OAuth2 token."' % self.app.config['site_id']}
                    self.abort(401, 'invalid oauth2 token', headers=headers)
        elif self.debug and self.request.get('user'):
            self.uid = self.request.get('user')
        elif self.request.user_agent.startswith('SciTran'):
            if self.request.environ['SSL_CLIENT_VERIFY'] != 'SUCCESS':
                self.abort(401, 'no valid SSL client certificate')
            if self.request.user_agent.startswith('SciTran Instance'):
                self.uid = self.request.headers.get('X-User')
                self.source_site = self.request.headers.get('X-Site')
                remote_instance = self.request.user_agent.replace('SciTran Instance', '').strip()
                if not self.app.db.sites.find_one({'_id': remote_instance}):
                    self.abort(402, remote_instance + ' is not an authorized remote instance')
            else:
                drone_type, drone_id = self.request.user_agent.replace('SciTran', '').strip().split()
                if not self.app.db.drones.find_one({'_id': drone_id}):
                    self.abort(402, drone_id + ' is not an authorized drone')
                self.drone_request = True
        self.public_request = not bool(self.uid)
        log.debug('public request: %s' % str(self.public_request))
        if self.drone_request and not self.source_site:  # engine request
            self.public_request = False
            self.superuser_request = True
        elif self.public_request or self.source_site:
            self.superuser_request = False
        else:
            user = self.app.db.users.find_one({'_id': self.uid}, ['root', 'wheel'])
            if not user:
                if self.app.config['demo']:
                    self.app.db.users.insert({
                        '_id': self.uid,
                        'email': self.uid,
                        'email_hash': hashlib.md5(self.uid).hexdigest(),
                        'firstname': identity.get('given_name', 'Firstname'),
                        'lastname': identity.get('family_name', 'Lastname'),
                        'wheel': True,
                        'root': True,
                    })
                    user = self.app.db.users.find_one({'_id': self.uid}, ['root', 'wheel'])
                else:
                    self.abort(403, 'user ' + self.uid + ' does not exist')
            self.superuser_request = user.get('root') and user.get('wheel')

    def dispatch(self):
        """dispatching and request forwarding"""
        target_site = self.request.get('site', self.app.config['site_id'])
        if target_site == self.app.config['site_id']:
            log.debug('from %s %s %s %s %s' % (self.source_site, self.uid, self.request.method, self.request.path, str(self.request.params.mixed())))
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
            self.params = self.request.params.mixed()
            if 'user' in self.params: del self.params['user']
            del self.params['site']
            log.debug(' for %s %s %s %s %s' % (target_site, self.uid, self.request.method, self.request.path, str(self.request.params.mixed())))
            target_uri = target['api_uri'] + self.request.path.split('/api')[1]
            r = requests.request(self.request.method, target_uri,
                    params=self.params, data=self.request.body, headers=self.headers, cert=self.app.config['ssl_cert'])
            if r.status_code != 200:
                self.abort(r.status_code, 'InterNIMS p2p err: ' + r.reason)
            self.response.write(r.content)

    def abort(self, code, *args, **kwargs):
        log.warning(str(code) + ' ' + '; '.join(args))
        json_body = {
                'uid': self.uid,
                'code': code,
                'detail': '; '.join(args),
                }
        webapp2.abort(code, *args, json_body=json_body, **kwargs)

    def schema(self, updates={}):
        json_schema = copy.deepcopy(self.json_schema)
        json_schema['properties'].update(updates)
        return json_schema
