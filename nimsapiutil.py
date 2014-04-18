# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
log = logging.getLogger('nimsapi')
logging.getLogger('requests').setLevel(logging.WARNING)                  # silence Requests library logging

import json
import base64
import webapp2
import datetime
import requests
import bson.json_util
import Crypto.Hash.SHA
import Crypto.PublicKey.RSA
import Crypto.Signature.PKCS1_v1_5

INTEGER_ROLES = {
        'anon-read':  0,
        'read-only':  1,
        'read-write': 2,
        'admin':      3,
        }


class NIMSRequestHandler(webapp2.RequestHandler):

    """fetches pubkey from own self.db.remotes. needs to be aware of OWN site uid"""

    json_schema = None

    file_schema = {
        'title': 'File',
        'type': 'object',
        'properties': {
            'type': {
                'title': 'Type',
                'type': 'array',
            },
            'filename': {
                'title': 'File Name',
                'type': 'string',
            },
            'ext': {
                'title': 'File Name Extension',
                'type': 'string',
            },
            'md5': {
                'title': 'MD5',
                'type': 'string',
            },
            'size': {
                'title': 'Size',
                'type': 'integer',
            },
        }
    }

    def __init__(self, request=None, response=None):
        self.initialize(request, response)
        self.target_id = self.request.get('site', None)
        self.access_token = self.request.headers.get('Authorization', None)

        # CORS header
        if 'Origin' in self.request.headers and self.request.headers['Origin'].startswith('https://'):
            self.response.headers['Access-Control-Allow-Origin'] = self.request.headers['Origin']

        if self.access_token and self.app.config['oauth2_id_endpoint']:
            r = requests.get(self.app.config['oauth2_id_endpoint'], headers={'Authorization': 'Bearer ' + self.access_token})
            if r.status_code == 200:
                self.uid = json.loads(r.content)['email']
            else:
                # TODO: add handlers for bad tokens
                # inform app of expired token, app will try to get new token, or ask user to log in again
                log.debug('ERR: ' + str(r.status_code) + r.reason + ' bad token')
        elif self.app.config['insecure'] and 'X-Requested-With' not in self.request.headers and self.request.get('user', None):
            self.uid = self.request.get('user')
        else:
            self.uid = '@public'
            self.user_is_superuser = False

        if self.uid != '@public':
            user = self.app.db.users.find_one({'_id': self.uid}, ['superuser'])
            if user:
                self.user_is_superuser = user.get('superuser', None)
            else:
                self.abort(403, 'user ' + self.uid + ' does not exist')

        if self.target_id not in [None, self.app.config['site_id']]:
            self.rtype = 'to_remote'

            if not self.app.config['site_id']:
                self.abort(500, 'api site_id is not configured')
            if not self.app.config['ssl_key']:
                self.abort(500, 'api ssl_key is not configured')

            target = self.app.db.remotes.find_one({'_id': self.target_id}, {'_id': False, 'api_uri': True})
            if not target:
                self.abort(402, 'remote host ' + self.target_id + ' is not an authorized remote')

            # adjust headers
            self.headers = self.request.headers
            self.headers['User-Agent'] = 'NIMS Instance ' + self.app.config['site_id']
            self.headers['X-From'] = (self.uid + '#' + self.app.config['site_id']) if self.uid != '@public' else self.uid
            self.headers['Content-Length'] = len(self.request.body)
            self.headers['Date'] = str(datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S'))   # Nonce for msg
            del self.headers['Host']
            if self.headers.get('Authorization'): del self.headers['Authorization']

            # adjust params
            self.params = self.request.params.mixed()
            if self.params.get('user'): del self.params['user']
            del self.params['site']

            # assemble msg, hash, and signature
            msg = self.request.method + self.request.path + str(self.params) + self.request.body + self.headers.get('Date')
            signature = Crypto.Signature.PKCS1_v1_5.new(self.app.config['ssl_key']).sign(Crypto.Hash.SHA.new(msg))
            self.headers['X-Signature'] = base64.b64encode(signature)

            # prepare delegated request URI
            self.target_uri = target['api_uri'] + self.request.path.split('/nimsapi')[1]

        elif self.request.user_agent.startswith('NIMS Instance'):
            self.rtype = 'from_remote'

            self.uid = self.request.headers.get('X-From')
            self.user_is_superuser = False

            remote_instance = self.request.user_agent.replace('NIMS Instance', '').strip()
            requester = self.app.db.remotes.find_one({'_id': remote_instance})
            if not requester:
                self.abort(402, remote_instance + ' is not authorized')

            # assemble msg, hash, and verify received signature
            signature = base64.b64decode(self.request.headers.get('X-Signature'))
            msg = self.request.method + self.request.path + str(self.request.params.mixed()) + self.request.body + self.request.headers.get('Date')
            verifier = Crypto.Signature.PKCS1_v1_5.new(Crypto.PublicKey.RSA.importKey(requester['pubkey']))
            if not verifier.verify(Crypto.Hash.SHA.new(msg), signature):
                self.abort(402, 'remote message/signature is not authentic')
        else:
            self.rtype = 'local'

    def dispatch(self):
        """dispatching and request forwarding"""
        log.debug(self.rtype + ' ' + self.uid + ' ' + self.request.method + ' ' + self.request.path + ' ' + str(self.request.params.mixed()))
        if self.rtype in ['local', 'from_remote']:
            return super(NIMSRequestHandler, self).dispatch()
        else:
            if self.request.method == 'OPTIONS':
                return self.options()
            r = requests.request(self.request.method, self.target_uri, params=self.params, data=self.request.body, headers=self.headers, verify=False)
            if r.status_code != 200:
                self.abort(r.status_code, 'InterNIMS p2p err: ' + r.reason)
            self.response.write(r.content)

    def abort(self, code, *args, **kwargs):
        log.warning(str(code) + ' ' + '; '.join(args))
        if 'Access-Control-Allow-Origin' in self.response.headers:
            headers = kwargs.setdefault('headers', {})
            headers['Access-Control-Allow-Origin'] = self.response.headers['Access-Control-Allow-Origin']
        webapp2.abort(code, *args, **kwargs)

    def options(self, *args, **kwargs):
        self.response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, POST, PUT, DELETE, OPTIONS'
        self.response.headers['Access-Control-Allow-Headers'] = 'Authorization'
        self.response.headers['Access-Control-Max-Age'] = '151200'

    def schema(self):
        if self.request.method == 'OPTIONS':
            return self.options()
        return self.json_schema

    def get_collection(self, cid, min_role=None):
        collection = self.app.db.collections.find_one({'_id': cid})
        if not collection:
            self.abort(404, 'no such Collection')
        if not self.user_is_superuser:
            coll = self.app.db.collections.find_one({'_id': cid, 'permissions.uid': self.uid}, ['permissions.$'])
            if not coll:
                self.abort(403, self.uid + ' does not have permissions on this Collection')
            if min_role and INTEGER_ROLES[coll['permissions'][0]['role']] < INTEGER_ROLES[min_role]:
                self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this Collection')
            if coll['permissions'][0]['role'] != 'admin': # if not admin, mask permissions of other users
                collection['permissions'] = coll['permissions']
        return collection

    def get_experiment(self, xid, min_role=None):
        experiment = self.app.db.experiments.find_one({'_id': xid})
        if not experiment:
            self.abort(404, 'no such Experiment')
        if not self.user_is_superuser:
            exp = self.app.db.experiments.find_one({'_id': xid, 'permissions.uid': self.uid}, ['permissions.$'])
            if not exp:
                self.abort(403, self.uid + ' does not have permissions on this Experiment')
            if min_role and INTEGER_ROLES[exp['permissions'][0]['role']] < INTEGER_ROLES[min_role]:
                self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this Experiment')
            if exp['permissions'][0]['role'] != 'admin': # if not admin, mask permissions of other users
                experiment['permissions'] = exp['permissions']
        return experiment

    def get_session(self, sid, min_role=None):
        session = self.app.db.sessions.find_one({'_id': sid})
        if not session:
            self.abort(404, 'no such Session')
        if not self.user_is_superuser:
            experiment = self.app.db.experiments.find_one({'_id': session['experiment'], 'permissions.uid': self.uid}, ['permissions.$'])
            if not experiment:
                if not self.app.db.experiments.find_one({'_id': session['experiment']}, []):
                    self.abort(500)
                else:
                    self.abort(403, self.uid + ' does not have permissions to this Session')
            if min_role and INTEGER_ROLES[experiment['permissions'][0]['role']] < INTEGER_ROLES[min_role]:
                self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this Session')
        return session

    def get_epoch(self, eid, min_role=None):
        epoch = self.app.db.epochs.find_one({'_id': eid})
        if not epoch:
            self.abort(404, 'no such Epoch')
        if not self.user_is_superuser:
            session = self.app.db.sessions.find_one({'_id': epoch['session']}, ['experiment'])
            if not session:
                self.abort(500)
            experiment = self.app.db.experiments.find_one({'_id': session['experiment'], 'permissions.uid': self.uid}, ['permissions.$'])
            if not experiment:
                if not self.app.db.experiments.find_one({'_id': session['experiment']}, []):
                    self.abort(500)
                else:
                    self.abort(403, self.uid + ' does not have permissions on this Epoch')
            if min_role and INTEGER_ROLES[experiment['permissions'][0]['role']] < INTEGER_ROLES[min_role]:
                self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this Epoch')
        return epoch
