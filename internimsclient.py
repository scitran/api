#!/usr/bin/env python
#
# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
import logging.config
log = logging.getLogger('internims')
logging.getLogger('requests').setLevel(logging.WARNING)

import re
import json
import base64
import datetime
import requests
import Crypto.Hash.SHA
import Crypto.PublicKey.RSA
import Crypto.Signature.PKCS1_v1_5


def update(db, api_uri, site_name, site_id, privkey, internims_url):
    """sends is-alive signal to internims central."""
    exp_userlist = [e['permissions'] for e in db.experiments.find(None, {'_id': False, 'permissions.uid': True})]
    col_userlist = [c['permissions'] for c in db.collections.find(None, {'_id': False, 'permissions.uid': True})]
    remote_users = list(set([user['uid'] for container in exp_userlist+col_userlist for user in container if '#' in user['uid']]))

    payload = json.dumps({'site': site_id, 'api_uri': api_uri, 'users': remote_users, 'name': site_name})
    h = Crypto.Hash.SHA.new(payload)
    signature = Crypto.Signature.PKCS1_v1_5.new(privkey).sign(h)
    headers = {'Authorization': base64.b64encode(signature)}

    r = requests.post(internims_url, data=payload, headers=headers)
    if r.status_code == 200:
        response = (json.loads(r.content))
        # update remotes entries
        for site in response['sites']:
            site['timestamp'] = datetime.datetime.strptime(site['timestamp'], '%Y-%m-%dT%H:%M:%S.%fZ')
            db.remotes.update({'_id': site['_id']}, site, upsert=True)
        log.debug('updating remotes: ' + ', '.join((r['_id'] for r in response['sites'])))

        # delete remotes from users, who no longer have remotes
        db.users.update({'remotes': {'$exists': True}, '_id': {'$nin': response['users'].keys()}}, {'$unset': {'remotes': ''}}, multi=True)

        # add remotes to users
        log.debug('users w/ remotes: ' + ', '.join(response['users']))
        for uid, remotes in response['users'].iteritems():
            db.users.update({'_id': uid}, {'$set': {'remotes': remotes}})
        return True
    else:
        # r.reason contains generic description for the specific error code
        # need the part of the error response body that contains the detailed explanation
        reason = re.search('<br /><br />\n(.*)\n\n\n </body>\n</html>', r.content)
        log.warning((r.status_code, reason.group(1)))
        return False


def clean_remotes(db):
    """removes db.remotes, and removes remotes field from all db.users"""
    log.debug('removing remotes from users, and remotes collection')
    db.remotes.remove({})
    db.users.update({'remotes': {'$exists': True}}, {'$unset': {'remotes': ''}}, multi=True)


if __name__ == '__main__':
    import os
    import sys
    import time
    import pymongo
    import argparse
    import ConfigParser

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('configfile',  help='path to configuration file')
    arg_parser.add_argument('--internims_url', help='https://internims.appspot.com')
    arg_parser.add_argument('--db_uri', help='DB URI')
    arg_parser.add_argument('--api_uri', help='API URL, without http:// or https://')
    arg_parser.add_argument('--site_id', help='instance ID')
    arg_parser.add_argument('--site_name', help='instance name')
    arg_parser.add_argument('--sleeptime', default=60, type=int, help='time to sleep between is alive signals')
    arg_parser.add_argument('--ssl_key', help='path to privkey file')
    args = arg_parser.parse_args()

    config = ConfigParser.ConfigParser({'here': os.path.dirname(os.path.abspath(args.configfile))})
    config.read(args.configfile)
    logging.config.fileConfig(args.configfile, disable_existing_loggers=False)

    privkey_file = args.ssl_key or config.get('nims', 'ssl_key')
    if privkey_file:
        try:
            privkey = Crypto.PublicKey.RSA.importKey(open(privkey_file).read())
        except Exception:
            log.warn(privkey_file + ' is not a valid private SSL key file, bailing out.')
            sys.exit(1)
        else:
            log.info('successfully loaded private SSL key from ' + privkey_file)
    else:
        log.warn('private SSL key not specified, bailing out.')
        sys.exit(1)

    db_uri = args.db_uri or config.get('nims', 'db_uri')
    db = (pymongo.MongoReplicaSetClient(db_uri) if 'replicaSet' in db_uri else pymongo.MongoClient(db_uri)).get_default_database()

    site_name = args.site_name or config.get('nims', 'site_name')
    site_id = args.site_id or config.get('nims', 'site_id')
    api_uri = args.api_uri or config.get('nims', 'api_uri')
    internims_url = args.internims_url or config.get('nims', 'internims_url')

    fail_count = 0

    while True:
        if not update(db, api_uri, site_name, site_id, privkey, internims_url):
            fail_count += 1
        else:
            fail_count = 0
        if fail_count == 3:
            log.debug('InterNIMS unreachable, purging all remotes info')
            clean_remotes(db)
        time.sleep(args.sleeptime)
