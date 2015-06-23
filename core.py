# @author:  Gunnar Schaefer, Kevin S. Hahn

import logging
log = logging.getLogger('scitran.api')

import os
import re
import gzip
import json
import shutil
import hashlib
import tarfile
import datetime
import lockfile
import markdown
import jsonschema
import bson

import base
import util
import users
import zipstream
import tempdir as tempfile

UPLOAD_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Upload',
    'type': 'object',
    'properties': {
        'filetype': {
            'type': 'string',
        },
        'overwrite': {
            'type': 'object',
            'properties': {
                'group_name': {
                    'type': 'string',
                },
                'project_name': {
                    'type': 'string',
                },
                'series_uid': {
                    'type': 'string',
                },
                'acq_no': {
                    'type': 'integer',
                },
            },
            'required': ['group_name', 'project_name', 'series_uid'],
            'additionalProperties': False,
        },
    },
    'required': ['filetype', 'overwrite'],
    'additionalProperties': False,
}

DOWNLOAD_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Download',
    'type': 'object',
    'properties': {
        'optional': {
            'type': 'boolean',
        },
        'nodes': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'properties': {
                    'level': {
                        'type': 'string',
                        'enum': ['project', 'session', 'acquisition'],
                    },
                    '_id': {
                        'type': 'string',
                        'pattern': '^[0-9a-f]{24}$',
                    },
                },
                'required': ['level', '_id'],
                'additionalProperties': False
            },
        },
    },
    'required': ['optional', 'nodes'],
    'additionalProperties': False
}

RESET_SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'Reset',
    'type': 'object',
    'properties': {
        'reset': {
            'type': 'boolean',
        },
    },
    'required': ['reset'],
    'additionalProperties': False
}


class Core(base.RequestHandler):

    """/api """

    def head(self):
        """Return 200 OK."""
        pass

    def post(self):
        try:
            payload = self.request.json_body
            jsonschema.validate(payload, RESET_SCHEMA)
        except (ValueError, jsonschema.ValidationError) as e:
            self.abort(400, str(e))
        if payload.get('reset', False):
            self.app.db.projects.delete_many({})
            self.app.db.sessions.delete_many({})
            self.app.db.acquisitions.delete_many({})
            self.app.db.collections.delete_many({})
            self.app.db.jobs.delete_many({})
            for p in (self.app.config['data_path'] + '/' + d for d in os.listdir(self.app.config['data_path'])):
                if p not in [self.app.config['upload_path'], self.app.config['quarantine_path']]:
                    shutil.rmtree(p)

    def get(self):
        """Return API documentation"""
        resources = """
            Resource                            | Description
            :-----------------------------------|:-----------------------
            [(/sites)]                          | local and remote sites
            /upload                             | upload
            /download                           | download
            [(/search)]                         | search
            [(/users)]                          | list of users
            [(/users/count)]                    | count of users
            [(/users/self)]                     | user identity
            [(/users/roles)]                    | user roles
            [(/users/schema)]                   | schema for single user
            /users/*<uid>*                      | details for user *<uid>*
            [(/groups)]                         | list of groups
            [(/groups/count)]                   | count of groups
            [(/groups/schema)]                  | schema for single group
            /groups/*<gid>*                     | details for group *<gid>*
            /groups/*<gid>*/projects            | list of projects for group *<gid>*
            /groups/*<gid>*/sessions            | list of sessions for group *<gid>*
            [(/projects)]                       | list of projects
            [(/projects/count)]                 | count of projects
            [(/projects/groups)]                | groups for projects
            [(/projects/schema)]                | schema for single project
            /projects/*<pid>*                   | details for project *<pid>*
            /projects/*<pid>*/sessions          | list sessions for project *<pid>*
            [(/sessions/count)]                 | count of sessions
            [(/sessions/schema)]                | schema for single session
            /sessions/*<sid>*                   | details for session *<sid>*
            /sessions/*<sid>*/move              | move session *<sid>* to a different project
            /sessions/*<sid>*/acquisitions      | list acquisitions for session *<sid>*
            [(/acquisitions/count)]             | count of acquisitions
            [(/acquisitions/schema)]            | schema for single acquisition
            /acquisitions/*<aid>*               | details for acquisition *<aid>*
            [(/collections)]                    | list of collections
            [(/collections/count)]              | count of collections
            [(/collections/schema)]             | schema for single collection
            /collections/*<cid>*                | details for collection *<cid>*
            /collections/*<cid>*/sessions       | list of sessions for collection *<cid>*
            /collections/*<cid>*/acquisitions   | list of acquisitions for collection *<cid>*
            """

        if self.debug and self.uid:
            resources = re.sub(r'\[\((.*)\)\]', r'[\1](/api\1?user=%s)' % self.uid, resources)
        else:
            resources = re.sub(r'\[\((.*)\)\]', r'[\1](/api\1)', resources)
        resources = resources.replace('<', '&lt;').replace('>', '&gt;').strip()

        self.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        self.response.write('<html>\n')
        self.response.write('<head>\n')
        self.response.write('<title>SciTran API</title>\n')
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
        if self.debug and not self.request.get('user', None):
            self.response.write('<form name="username" action="" method="get">\n')
            self.response.write('Username: <input type="text" name="user">\n')
            self.response.write('<input type="submit" value="Generate Custom Links">\n')
            self.response.write('</form>\n')
        self.response.write(markdown.markdown(resources, ['extra']))
        self.response.write('</body>\n')
        self.response.write('</html>\n')

    def put(self):
        """Receive a sortable reaper or user upload."""
        #if not self.uid and not self.drone_request:
        #    self.abort(402, 'uploads must be from an authorized user or drone')
        if 'Content-MD5' not in self.request.headers:
            self.abort(400, 'Request must contain a valid "Content-MD5" header.')
        filename = self.request.headers.get('Content-Disposition', '').partition('filename=')[2].strip('"')
        if not filename:
            self.abort(400, 'Request must contain a valid "Content-Disposition" header.')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=self.app.config['upload_path']) as tempdir_path:
            filepath = os.path.join(tempdir_path, filename)
            success, sha1sum = util.receive_stream_and_validate(self.request.body_file, filepath, self.request.headers['Content-MD5'])
            if not success:
                self.abort(400, 'Content-MD5 mismatch.')
            if not tarfile.is_tarfile(filepath):
                self.abort(415, 'Only tar files are accepted.')
            log.info('Received    %s [%s] from %s' % (filename, util.hrsize(self.request.content_length), self.request.user_agent))
            fileinfo = util.parse_file(filepath, sha1sum)
            if fileinfo is None:
                util.quarantine_file(filepath, self.app.config['quarantine_path'])
                self.abort(202, 'Quarantining %s (unparsable)' % filename)
            util.commit_file(self.app.db.acquisitions, None, fileinfo, filepath, self.app.config['data_path'])

    def upload(self):
        """
        Recieve a multi-file upload.

        3 phases:
            1 - upload metadata, obtain upload ticket
            2 - upload files, one at a time, but in parallel
            3 - send a 'complete' message
        """

        def store_file(fd, filename, md5, arcpath, arcname):
            with tempfile.TemporaryDirectory(prefix='.tmp', dir=self.app.config['upload_path']) as tempdir_path:
                filepath = os.path.join(tempdir_path, filename)
                success, _ = util.receive_stream_and_validate(fd, filepath, md5)
                if not success:
                    self.abort(400, 'Content-MD5 mismatch.')
                with lockfile.LockFile(arcpath):
                    with tarfile.open(arcpath, 'a') as archive:
                        archive.add(filepath, os.path.join(arcname, filename))

        if self.public_request:
            self.abort(403, 'must be logged in to upload data')

        filename = self.request.get('filename')
        ticket_id = self.request.get('ticket')
        if not ticket_id:
            if filename != 'METADATA.json':
                self.abort(400, 'first file must be METADATA.json')
            try:
                json_body = self.request.json_body
                jsonschema.validate(json_body, UPLOAD_SCHEMA)
            except (ValueError, jsonschema.ValidationError) as e:
                self.abort(400, str(e))
            filetype = json_body['filetype']
            overwrites = json_body['overwrite']

            query = {'name': overwrites['project_name'], 'group': overwrites['group_name']}
            project = self.app.db.projects.find_one(query) # verify permissions
            if not self.superuser_request:
                user_perm = util.user_perm(project['permissions'], self.uid)
                if not user_perm:
                    self.abort(403, self.uid + ' does not have permissions on this project')
                if users.INTEGER_ROLES[user_perm['access']] < users.INTEGER_ROLES['rw']:
                    self.abort(403, self.uid + ' does not have at least ' + min_role + ' permissions on this project')

            # give the interior directory the same name the reaper would give
            acq_no = overwrite.get('acq_no', 1) if overwrite.get('manufacturer', '').upper() != 'SIEMENS' else None
            arcname = overwrite.get('series_uid', '') + ('_' + str(acq_no) if acq_no is not None else '') + '_' + filetype
            upload_id = str(bson.ObjectId())
            log.debug('creating new temporary file %s' % upload_id)
            fp = os.path.join(upload_path, upload_id + '.tar')
            status, detail = write_to_tar(fp, 'w', 'METADATA.json', self.request.body_file, content_md5, arcname)
            if status != 200:
                self.abort(status, detail)
            else:
                return upload_id

        elif upload_id and filename and not complete:
            log.debug('appending to %s' % upload_id)
            fp = os.path.join(upload_path, upload_id + '.tar')
            status, detail = write_to_tar(fp, 'a', filename, self.request.body_file, content_md5)  # don't know arcname anymore...
            if status != 200:
                self.abort(status, detail)

        elif upload_id and complete:
            fp = os.path.join(upload_path, upload_id + '.tar')
            log.debug('completing %s' % fp)
            with tempfile.TemporaryDirectory() as tempdir_path:
                log.debug('working in tempdir %s' % tempdir_path)
                zip_fp = os.path.join(tempdir_path, upload_id + '.tgz')
                with tarfile.open(zip_fp,'w:gz', compresslevel=6) as zf: # zip of tarfile was not being recognized by scitran.data
                    with tarfile.open(fp, 'r') as tf:
                        for ti in tf.getmembers():
                            zf.addfile(ti, tf.extractfile(ti))
                hash_ = hashlib.sha1()
                with open(zip_fp, 'rb') as fd:
                    while True:
                        chunk = fd.read(2**20)
                        if not chunk:
                            break
                        hash_.update(chunk)
                log.debug('inserting')
                status, detail = util.insert_file(self.app.db.acquisitions, None, None, zip_fp, hash_.hexdigest(), self.app.config['data_path'], self.app.config['quarantine_path'])
                if status != 200:
                    self.abort(status, detail)
                os.remove(fp)  # always remove the original tar upon 'complete'. complete file is sorted or quarantined.
        else:
            self.abort(400, 'Expected _id (str), filename (str), and/or complete (bool) parameters and binary file content as body')

    def _preflight_archivestream(self, req_spec):
        data_path = self.app.config['data_path']
        arc_prefix = 'sdm'

        def append_targets(targets, container, prefix, total_size, total_cnt):
            prefix = arc_prefix + '/' + prefix
            for f in container['files']:
                if req_spec['optional'] or not f.get('optional', False):
                    filepath = os.path.join(data_path, str(container['_id'])[-3:] + '/' + str(container['_id']), f['filename'])
                    if os.path.exists(filepath): # silently skip missing files
                        targets.append((filepath, prefix + '/' + f['filename'], f['filesize']))
                        total_size += f['filesize']
                        total_cnt += 1
            return total_size, total_cnt

        file_cnt = 0
        total_size = 0
        targets = []
        # FIXME: check permissions of everything
        for item in req_spec['nodes']:
            item_id = bson.ObjectId(item['_id'])
            if item['level'] == 'project':
                project = self.app.db.projects.find_one({'_id': item_id}, ['group', 'name', 'files'])
                prefix = project['group'] + '/' + project['name']
                total_size, file_cnt = append_targets(targets, project, prefix, total_size, file_cnt)
                sessions = self.app.db.sessions.find({'project': item_id}, ['label', 'files'])
                for session in sessions:
                    session_prefix = prefix + '/' + session.get('label', 'untitled')
                    total_size, file_cnt = append_targets(targets, session, session_prefix, total_size, file_cnt)
                    acquisitions = self.app.db.acquisitions.find({'session': session['_id']}, ['label', 'files'])
                    for acq in acquisitions:
                        acq_prefix = session_prefix + '/' + acq.get('label', 'untitled')
                        total_size, file_cnt = append_targets(targets, acq, acq_prefix, total_size, file_cnt)
            elif item['level'] == 'session':
                session = self.app.db.sessions.find_one({'_id': item_id}, ['project', 'label', 'files'])
                project = self.app.db.projects.find_one({'_id': session['project']}, ['group', 'name'])
                prefix = project['group'] + '/' + project['name'] + '/' + session.get('label', 'untitled')
                total_size, file_cnt = append_targets(targets, session, prefix, total_size, file_cnt)
                acquisitions = self.app.db.acquisitions.find({'session': item_id}, ['label', 'files'])
                for acq in acquisitions:
                    acq_prefix = prefix + '/' + acq.get('label', 'untitled')
                    total_size, file_cnt = append_targets(targets, acq, acq_prefix, total_size, file_cnt)
            elif item['level'] == 'acquisition':
                acq = self.app.db.acquisitions.find_one({'_id': item_id}, ['session', 'label', 'files'])
                session = self.app.db.sessions.find_one({'_id': acq['session']}, ['project', 'label'])
                project = self.app.db.projects.find_one({'_id': session['project']}, ['group', 'name'])
                prefix = project['group'] + '/' + project['name'] + '/' + session.get('label', 'untitled') + '/' + acq.get('label', 'untitled')
                total_size, file_cnt = append_targets(targets, acq, prefix, total_size, file_cnt)
        log.debug(json.dumps(targets, sort_keys=True, indent=4, separators=(',', ': ')))
        filename = 'sdm_' + datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.zip'
        ticket = util.download_ticket('batch', targets, filename, total_size)
        self.app.db.downloads.insert(ticket)
        return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size}

    def _archivestream(self, ticket):
        length = None # FIXME compute actual length
        z = zipstream.ZipFile(allowZip64=True)
        targets = ticket['target']
        for filepath, acrpath, _ in targets:
            z.write(filepath, acrpath)
        return z, length

    def download(self):
        ticket_id = self.request.get('ticket')
        if ticket_id:
            ticket = self.app.db.downloads.find_one({'_id': ticket_id})
            if not ticket:
                self.abort(404, 'no such ticket')
            self.response.app_iter, length = self._archivestream(ticket)
            self.response.headers['Content-Length'] = str(length) # must be set after setting app_iter
            self.response.headers['Content-Type'] = 'application/octet-stream'
            self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(ticket['filename'])
        else:
            try:
                req_spec = self.request.json_body
                jsonschema.validate(req_spec, DOWNLOAD_SCHEMA)
            except (ValueError, jsonschema.ValidationError) as e:
                self.abort(400, str(e))
            log.debug(json.dumps(req_spec, sort_keys=True, indent=4, separators=(',', ': ')))
            return self._preflight_archivestream(req_spec)

    def sites(self):
        """Return local and remote sites."""
        projection = ['name', 'onload']
        # TODO onload for local is true
        if self.public_request or self.request.get('all').lower() in ('1', 'true'):
            sites = list(self.app.db.sites.find(None, projection))
        else:
            # TODO onload based on user prefs
            remotes = (self.app.db.users.find_one({'_id': self.uid}, ['remotes']) or {}).get('remotes', [])
            remote_ids = [r['_id'] for r in remotes] + [self.app.config['site_id']]
            sites = list(self.app.db.sites.find({'_id': {'$in': remote_ids}}, projection))
        for s in sites:  # TODO: this for loop will eventually move to public case
            if s['_id'] == self.app.config['site_id']:
                s['onload'] = True
                break
        return sites

    search_schema = {
        'title': 'Search',
        'type': 'array',
        'items': [
            {
                'title': 'Session',
                'type': 'array',
                'items': [
                    {
                        'title': 'Date',
                        'type': 'date',
                        'field': 'session.date',
                    },
                    {
                        'title': 'Subject',
                        'type': 'array',
                        'items': [
                            {
                                'title': 'Name',
                                'type': 'array',
                                'items': [
                                    {
                                        'title': 'First',
                                        'type': 'string',
                                        'field': 'session.subject.firstname',
                                    },
                                    {
                                        'title': 'Last',
                                        'type': 'string',
                                        'field': 'session.subject.lastname',
                                    },
                                ],
                            },
                            {
                                'title': 'Date of Birth',
                                'type': 'date',
                                'field': 'session.subject.dob',
                            },
                            {
                                'title': 'Sex',
                                'type': 'string',
                                'enum': ['male', 'female'],
                                'field': 'session.subject.sex',
                            },
                        ],
                    },
                ],
            },
            {
                'title': 'MR',
                'type': 'array',
                'items': [
                    {
                        'title': 'Scan Type',
                        'type': 'string',
                        'enum': ['anatomical', 'fMRI', 'DTI'],
                        'field': 'acquisition.type',
                    },
                    {
                        'title': 'Echo Time',
                        'type': 'number',
                        'field': 'acquisition.echo_time',
                    },
                    {
                        'title': 'Size',
                        'type': 'array',
                        'items': [
                            {
                                'title': 'X',
                                'type': 'integer',
                                'field': 'acquisition.size.x',
                            },
                            {
                                'title': 'Y',
                                'type': 'integer',
                                'field': 'acquisition.size.y',
                            },
                        ],
                    },
                ],
            },
            {
                'title': 'EEG',
                'type': 'array',
                'items': [
                    {
                        'title': 'Electrode Count',
                        'type': 'integer',
                        'field': 'acquisition.electrode_count',
                    },
                ],
            },
        ],
    }

    def search(self):
        """Search."""
        SEARCH_POST_SCHEMA = {
            '$schema': 'http://json-schema.org/draft-04/schema#',
            'title': 'File',
            'type': 'object',
            'properties': {
                'subj_code': {
                    'title': 'Subject Code',
                    'type': 'string',
                },
                'subj_firstname': {
                    'title': 'Subject First Name',   # hash
                    'type': 'string',
                },
                'subj_lastname': {
                    'title': 'Subject Last Name',
                    'type': 'string',
                },
                'scan_type': {  # MR SPECIFIC!!!
                    'title': 'Scan Type',
                    'enum': self.app.db.acquisitions.distinct('datatype')
                },
                'date_from': {
                    'title': 'Date From',
                    'type': 'string',
                },
                'date_to': {
                    'title': 'Date To',
                    'type': 'string',
                },
                'psd': {  # MR SPECIFIC!!!
                    'title': 'PSD Name',
                    'type': 'string',   # 'enum': self.app.db.acquisitions.distinct('psd'),
                },
                'subj_age_max': {  # age in years
                    'title': 'Subject Age Max',
                    'type': 'integer',
                },
                'subj_age_min': {  # age in years
                    'title': 'Subject Age Min',
                    'type': 'integer',
                },
                'exam': {
                    'title': 'Exam Number',
                    'type': 'integer',
                },
                'description': {
                    'title': 'Description',
                    'type': 'string',
                },
            },
            # 'required': ['subj_code', 'scan_type', 'date_from', 'date_to', 'psd_name', 'operator', 'subj_age_max', 'subj_age_min', 'exam'],
            # 'additionalProperties': False
        }
        if self.request.method == 'GET':
            return SEARCH_POST_SCHEMA
        try:
            json_body = self.request.json_body
            jsonschema.validate(json_body, SEARCH_POST_SCHEMA)
        except (ValueError, jsonschema.ValidationError) as e:
            self.abort(400, str(e))

        # TODO: search needs to include operator details? do types of datasets have an 'operator'?
        # TODO: provide a schema that allows directly using the request data, rather than
        # requiring construction of the queries....
        session_query = {}
        exam = json_body.get('exam')
        subj_code = json_body.get('subj_code')
        age_max = json_body.get('subj_age_max')
        age_min = json_body.get('subj_age_min')
        if exam:
            session_query.update({'exam': exam})
        if subj_code:
            session_query.update({'subject.code': subj_code})
        if age_min and age_max:
            session_query.update({'subject.age': {'$gte': age_min, '$lte': age_max}})
        elif age_max:
            session_query.update({'subject.age': {'$lte': age_max}})
        elif age_min:
            session_query.update({'subject.age': {'$gte': age_min}})

        # TODO: don't build these, want to get as close to dump the data from the request
        acq_query = {}
        psd = json_body.get('psd')
        types_kind = json_body.get('scan_type')
        time_fmt = '%Y-%m-%d'  # assume that dates will come in as "2014-01-01"
        description = json_body.get('description')
        date_to = json_body.get('date_to')  # need to do some datetime conversion
        if date_to:
            date_to = datetime.datetime.strptime(date_to, time_fmt)
        date_from = json_body.get('date_from')      # need to do some datetime conversion
        if date_from:
            date_from = datetime.datetime.strptime(date_from, time_fmt)
        if psd:
            acq_query.update({'psd': psd})
        if types_kind:
            acq_query.update({'datatype': types_kind})
        if date_to and date_from:
            acq_query.update({'timestamp': {'$gte': date_from, '$lte': date_to}})
        elif date_to:
            acq_query.update({'timestamp': {'$lte': date_to}})
        elif date_from:
            acq_query.update({'timestamp': {'$gte': date_from}})
        if description:
            # glob style matching, whole word must exist within description
            pass

        # also query sessions
        # permissions exist at the session level, which will limit the acquisition queries to sessions user has access to
        if not self.superuser_request:
            session_query['permissions'] = {'$elemMatch': {'_id': self.uid, 'site': self.source_site}}
            acq_query['permissions'] = {'$elemMatch': {'_id': self.uid, 'site': self.source_site}}
        sessions = list(self.app.db.sessions.find(session_query))
        session_ids = [s['_id'] for s in sessions]
        # first find the acquisitions that meet the acquisition level query params
        aquery = {'session': {'$in': session_ids}}
        aquery.update(acq_query)

        # build a more complex response, and clean out database specifics
        groups = []
        projects = []
        sessions = []
        acqs = list(self.app.db.acquisitions.find(aquery))
        for acq in acqs:
            session = self.app.db.sessions.find_one({'_id': acq['session']})
            project = self.app.db.projects.find_one({'_id': session['project']})
            group = project['group']
            del project['group']
            project['group'] = group
            acq['_id'] = str(acq['_id'])
            acq['session'] = str(acq['session'])
            session['_id'] = str(session['_id'])
            session['project'] = str(session['project'])
            project['_id'] = str(project['_id'])
            if session not in sessions:
                sessions.append(session)
            if project not in projects:
                projects.append(project)
            if group not in groups:
                groups.append(group)

        results = {
            'groups': groups,
            'projects': projects,
            'sessions': sessions,
            'acquisitions': acqs,
        }

        return results
