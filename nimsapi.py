#!/usr/bin/env python
#
# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
import logging.config
log = logging.getLogger('nimsapi')

import os
import re
import json
import uuid
import hashlib
import tarfile
import webapp2
import zipfile
import markdown
import bson.json_util
import webapp2_extras.routes
import Crypto.PublicKey.RSA

import users
import experiments
import nimsapiutil
import collections_
import tempdir as tempfile

def hrsize(size):
    if size < 1000:
        return '%d%s' % (size, 'B')
    for suffix in 'KMGTPEZY':
        size /= 1024.
        if size < 10.:
            return '%.1f%s' % (size, suffix)
        if size < 1000.:
            return '%.0f%s' % (size, suffix)
    return '%.0f%s' % (size, 'Y')


class NIMSAPI(nimsapiutil.NIMSRequestHandler):

    """/nimsapi """

    def head(self):
        """Return 200 OK."""
        self.response.set_status(200)

    def get(self):
        """Return API documentation"""
        resources = """
            Resource                                            | Description
            :---------------------------------------------------|:-----------------------
            nimsapi/login                                       | user login
            [(nimsapi/remotes)]                                 | list of remote instances
            nimsapi/upload                                      | upload
            nimsapi/download                                    | download
            [(nimsapi/log)]                                     | log messages
            [(nimsapi/users)]                                   | list of users
            [(nimsapi/users/count)]                             | count of users
            [(nimsapi/users/listschema)]                        | schema for user list
            [(nimsapi/users/schema)]                            | schema for single user
            nimsapi/users/*<uid>*                               | details for user *<uid>*
            [(nimsapi/groups)]                                  | list of groups
            [(nimsapi/groups/count)]                            | count of groups
            [(nimsapi/groups/listschema)]                       | schema for group list
            [(nimsapi/groups/schema)]                           | schema for single group
            nimsapi/groups/*<gid>*                              | details for group *<gid>*
            [(nimsapi/experiments)]                             | list of experiments
            [(nimsapi/experiments/count)]                       | count of experiments
            [(nimsapi/experiments/listschema)]                  | schema for experiment list
            [(nimsapi/experiments/schema)]                      | schema for single experiment
            nimsapi/experiments/*<xid>*                         | details for experiment *<xid>*
            nimsapi/experiments/*<xid>*/sessions                | list sessions for experiment *<xid>*
            [(nimsapi/sessions/count)]                          | count of sessions
            [(nimsapi/sessions/listschema)]                     | schema for sessions list
            [(nimsapi/sessions/schema)]                         | schema for single session
            nimsapi/sessions/*<sid>*                            | details for session *<sid>*
            nimsapi/sessions/*<sid>*/move                       | move session *<sid>* to a different experiment
            nimsapi/sessions/*<sid>*/epochs                     | list epochs for session *<sid>*
            [(nimsapi/epochs/count)]                            | count of epochs
            [(nimsapi/epochs/listschema)]                       | schema for epoch list
            [(nimsapi/epochs/schema)]                           | schema for single epoch
            nimsapi/epochs/*<eid>*                              | details for epoch *<eid>*
            [(nimsapi/collections)]                             | list of collections
            [(nimsapi/collections/count)]                       | count of collections
            [(nimsapi/collections/listschema)]                  | schema for collections list
            [(nimsapi/collections/schema)]                      | schema for single collection
            nimsapi/collections/*<cid>*                         | details for collection *<cid>*
            nimsapi/collections/*<cid>*/sessions                | list sessions for collection *<cid>*
            nimsapi/collections/*<cid>*/epochs?session=*<sid>*  | list of epochs for collection *<cid>*, optionally restricted to session *<sid>*
            """
        resources = re.sub(r'\[\((.*)\)\]', r'[\1](\1)', resources).replace('<', '&lt;').replace('>', '&gt;').strip()
        self.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        self.response.write('<html>\n')
        self.response.write('<head>\n')
        self.response.write('<title>NIMSAPI</title>\n')
        self.response.write('<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">\n')
        self.response.write('<style type="text/css">\n')
        self.response.write('table {width:0%; border-width:1px; padding: 0;border-collapse: collapse;}\n')
        self.response.write('table tr {border-top: 1px solid #b8b8b8; background-color: white; margin: 0; padding: 0;}\n')
        self.response.write('table tr:nth-child(2n) {background-color: #f8f8f8;}\n')
        self.response.write('table thead tr :last-child {width:100%;}\n')
        self.response.write('table tr th {font-weight: bold; border: 1px solid #b8b8b8; background-color: #cdcdcd; margin: 0; padding: 6px 13px;}\n')
        self.response.write('table tr th {font-weight: bold; border: 1px solid #b8b8b8; background-color: #cdcdcd; margin: 0; padding: 6px 13px;}\n')
        self.response.write('table tr td {border: 1px solid #b8b8b8; margin: 0; padding: 6px 13px;}\n')
        self.response.write('table tr th :first-child, table tr td :first-child {margin-top: 0;}\n')
        self.response.write('table tr th :last-child, table tr td :last-child {margin-bottom: 0;}\n')
        self.response.write('</style>\n')
        self.response.write('</head>\n')
        self.response.write('<body style="min-width:900px">\n')
        self.response.write(markdown.markdown(resources, ['extra']))
        self.response.write('</body>\n')
        self.response.write('</html>\n')

    def login(self):
        """Return details for the current User."""
        if self.request.method == 'OPTIONS':
            return self.options()
        log.debug(self.uid + ' has logged in')
        return self.app.db.users.find_and_modify({'_id': self.uid}, {'$inc': {'logins': 1}}, fields=['firstname', 'lastname', 'superuser'])

    def remotes(self):
        """Return the list of all remote sites."""
        if self.request.method == 'OPTIONS':
            return self.options()
        return [r['_id'] for r in self.app.db.remotes.find()]

    def upload(self):
        if self.request.method == 'OPTIONS':
            return self.options()
        # TODO add security: either authenticated user or machine-to-machine CRAM
        if 'Content-MD5' not in self.request.headers:
            self.abort(400, 'Request must contain a valid "Content-MD5" header.')
        filename = self.request.get('filename', 'anonymous')
        stage_path = self.app.config['stage_path']
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=stage_path) as tempdir_path:
            hash_ = hashlib.md5()
            upload_filepath = os.path.join(tempdir_path, filename)
            with open(upload_filepath, 'wb') as upload_file:
                for chunk in iter(lambda: self.request.body_file.read(2**20), ''):
                    hash_.update(chunk)
                    upload_file.write(chunk)
            if hash_.hexdigest() != self.request.headers['Content-MD5']:
                self.abort(400, 'Content-MD5 mismatch.')
            if not tarfile.is_tarfile(upload_filepath) and not zipfile.is_zipfile(upload_filepath):
                self.abort(415)
            log.info('upload from %s: %s [%s]' % (self.request.user_agent, os.path.basename(upload_filepath), hrsize(self.request.content_length)))
            os.rename(upload_filepath, os.path.join(stage_path, str(uuid.uuid1()) + '_' + filename)) # add UUID to prevent clobbering files

    def download(self):
        if self.request.method == 'OPTIONS':
            return self.options()
        paths = []
        symlinks = []
        for js_id in self.request.get('id', allow_multiple=True):
            type_, _id = js_id.split('_')
            _idpaths, _idsymlinks = resource_types[type_].download_info(_id)
            paths += _idpaths
            symlinks += _idsymlinks

    def log(self):
        """Return logs."""
        if self.request.method == 'OPTIONS':
            return self.options()
        try:
            logs = open(app.config['log_path']).readlines()
        except IOError as e:
            if 'Permission denied' in e:
                body_template = '${explanation}<br /><br />${detail}<br /><br />${comment}'
                comment = 'To fix permissions, run the following command: chmod o+r ' + app.config['log_path']
                self.abort(500, detail=str(e), comment=comment, body_template=body_template)
            else:
                self.abort(500, e) # file does not exist
        try:
            n = int(self.request.get('n', 10000))
        except:
            self.abort(400, 'n must be an integer')
        return [line.strip() for line in reversed(logs) if re.match('[-:0-9 ]{18} +nimsapi:(?!.*[/a-z]*/log )', line)][:n]


routes = [
    webapp2.Route(r'/nimsapi',                                          NIMSAPI),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi', [
        webapp2.Route(r'/login',                                        NIMSAPI, handler_method='login', methods=['OPTIONS', 'GET', 'POST']),
        webapp2.Route(r'/remotes',                                      NIMSAPI, handler_method='remotes', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/upload',                                       NIMSAPI, handler_method='upload', methods=['OPTIONS', 'PUT']),
        webapp2.Route(r'/download',                                     NIMSAPI, handler_method='download', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/log',                                          NIMSAPI, handler_method='log', methods=['OPTIONS', 'GET']),
    ]),
    webapp2.Route(r'/nimsapi/users',                                    users.Users),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi/users', [
        webapp2.Route(r'/count',                                        users.Users, handler_method='count', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/listschema',                                   users.Users, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/schema',                                       users.User, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/<uid>',                                        users.User),
    ]),
    webapp2.Route(r'/nimsapi/groups',                                   users.Groups),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi/groups', [
        webapp2.Route(r'/count',                                        users.Groups, handler_method='count', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/listschema',                                   users.Groups, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/schema',                                       users.Group, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/<gid>',                                        users.Group),
    ]),
    webapp2.Route(r'/nimsapi/experiments',                              experiments.Experiments),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi/experiments', [
        webapp2.Route(r'/count',                                        experiments.Experiments, handler_method='count', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/listschema',                                   experiments.Experiments, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/schema',                                       experiments.Experiment, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/<xid:[0-9a-f]{24}>',                           experiments.Experiment),
        webapp2.Route(r'/<xid:[0-9a-f]{24}>/sessions',                  experiments.Sessions),
    ]),
    webapp2.Route(r'/nimsapi/collections',                              collections_.Collections),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi/collections', [
        webapp2.Route(r'/count',                                        collections_.Collections, handler_method='count', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/listschema',                                   collections_.Collections, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/schema',                                       collections_.Collection, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/<cid:[0-9a-f]{24}>',                           collections_.Collection),
        webapp2.Route(r'/<cid:[0-9a-f]{24}>/sessions',                  collections_.Sessions),
        webapp2.Route(r'/<cid:[0-9a-f]{24}>/epochs',                    collections_.Epochs),
    ]),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi/sessions', [
        webapp2.Route(r'/count',                                        experiments.Sessions, handler_method='count', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/listschema',                                   experiments.Sessions, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/schema',                                       experiments.Session, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/<sid:[0-9a-f]{24}>',                           experiments.Session),
        webapp2.Route(r'/<sid:[0-9a-f]{24}>/epochs',                    experiments.Epochs),
    ]),
    webapp2_extras.routes.PathPrefixRoute(r'/nimsapi/epochs', [
        webapp2.Route(r'/count',                                        experiments.Epochs, handler_method='count', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/listschema',                                   experiments.Epochs, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/schema',                                       experiments.Epoch, handler_method='schema', methods=['OPTIONS', 'GET']),
        webapp2.Route(r'/<eid:[0-9a-f]{24}>',                           experiments.Epoch),
    ]),
]

def dispatcher(router, request, response):
    rv = router.default_dispatcher(request, response)
    if rv is not None:
        return response.write(json.dumps(rv, default=bson.json_util.default))

app = webapp2.WSGIApplication(routes, debug=True)
app.router.set_dispatcher(dispatcher)
app.config = dict(stage_path='', site_id='local', site_name='Local', ssl_key=None, insecure=False, log_path='')


if __name__ == '__main__':
    import sys
    import pymongo
    import argparse
    import ConfigParser
    import paste.httpserver

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('config_file', help='path to config file')
    arg_parser.add_argument('--db_uri', help='NIMS DB URI')
    arg_parser.add_argument('--stage_path', help='path to staging area')
    arg_parser.add_argument('--log_path', help='path to API log file')
    arg_parser.add_argument('--ssl_key', help='path to private SSL key file')
    arg_parser.add_argument('--site_id', help='InterNIMS site ID')
    arg_parser.add_argument('--site_name', help='InterNIMS site name')
    arg_parser.add_argument('--oauth2_id_endpoint', help='OAuth2 provider ID endpoint')
    args = arg_parser.parse_args()

    config = ConfigParser.ConfigParser({'here': os.path.dirname(os.path.abspath(args.config_file))})
    config.read(args.config_file)
    logging.config.fileConfig(args.config_file, disable_existing_loggers=False)
    logging.getLogger('paste.httpserver').setLevel(logging.INFO) # silence paste logging

    if args.ssl_key:
        try:
            ssl_key = Crypto.PublicKey.RSA.importKey(open(args.ssl_key).read())
        except:
            log.error(args.ssl_key + ' is not a valid private SSL key file, bailing out')
            sys.exit(1)
        else:
            log.debug('successfully loaded private SSL key from ' + args.ssl_key)
            app.config['ssl_key'] = ssl_key
    else:
        log.warning('private SSL key not specified, InterNIMS functionality disabled')

    app.config['site_id'] = args.site_id or app.config['site_id']
    app.config['site_name'] = args.site_name or app.config['site_name']
    app.config['stage_path'] = args.stage_path or config.get('nims', 'stage_path')
    app.config['log_path'] = args.log_path or app.config['log_path']
    app.config['oauth2_id_endpoint'] = args.oauth2_id_endpoint or config.get('oauth2', 'id_endpoint')
    app.config['insecure'] = config.getboolean('nims', 'insecure')

    db_uri = args.db_uri or config.get('nims', 'db_uri')
    app.db = (pymongo.MongoReplicaSetClient(db_uri) if 'replicaSet' in db_uri else pymongo.MongoClient(db_uri)).get_default_database()

    paste.httpserver.serve(app, port='8080')
