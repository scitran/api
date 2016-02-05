import os
import re
import bson
import copy
import json
import pytz
import tarfile
import datetime
import markdown
import cStringIO
import validators

from . import base
from . import util
from . import files
from . import rules
from . import config
from . import centralclient
from .dao import reaperutil, APIStorageException
from . import tempdir as tempfile

log = config.log

def _filter_check(property_filter, property_values):
    minus = set(property_filter.get('-', []))
    plus = set(property_filter.get('+', []))
    if not minus.isdisjoint(property_values):
        return False
    if plus and plus.isdisjoint(property_values):
        return False
    return True


def _append_targets(targets, container, prefix, total_size, total_cnt, optional, data_path, filters):
    for f in container.get('files', []):
        if filters:
            filtered = True
            for filter_ in filters:
                type_as_list = [f['type']] if f.get('type') else []
                if (
                    _filter_check(filter_.get('tags', {}), f.get('tags', [])) and
                    _filter_check(filter_.get('types', {}), type_as_list)
                    ):
                    filtered = False
                    break
            if filtered:
                continue
        if optional or not f.get('optional', False):
            filepath = os.path.join(data_path, util.path_from_hash(f['hash']))
            if os.path.exists(filepath): # silently skip missing files
                targets.append((filepath, prefix + '/' + f['name'], f['size']))
                total_size += f['size']
                total_cnt += 1
    return total_size, total_cnt


class Config(base.RequestHandler):

    def get(self):
        return config.get_public_config()

    def get_js(self):
        self.response.write(
            'config = ' +
            json.dumps( self.get(), sort_keys=True, indent=4, separators=(',', ': '), default=util.custom_json_serializer,) +
            ';'
        )


class Core(base.RequestHandler):

    """/api """

    def head(self):
        """Return 200 OK."""
        pass

    def get(self):
        """Return API documentation"""
        resources = """
            Resource                            | Description
            :-----------------------------------|:-----------------------
            [(/sites)]                          | local and remote sites
            /download                           | download
            [(/users)]                          | list of users
            [(/users/self)]                     | user identity
            [(/users/roles)]                    | user roles
            [(/users/*<uid>*)]                  | details for user *<uid>*
            [(/users/*<uid>*/groups)]           | groups for user *<uid>*
            [(/users/*<uid>*/projects)]         | projects for user *<uid>*
            [(/groups)]                         | list of groups
            /groups/*<gid>*                     | details for group *<gid>*
            /groups/*<gid>*/projects            | list of projects for group *<gid>*
            /groups/*<gid>*/sessions            | list of sessions for group *<gid>*
            [(/projects)]                       | list of projects
            [(/projects/groups)]                | groups for projects
            [(/projects/schema)]                | schema for single project
            /projects/*<pid>*                   | details for project *<pid>*
            /projects/*<pid>*/sessions          | list sessions for project *<pid>*
            [(/sessions)]                       | list of sessions
            [(/sessions/schema)]                | schema for single session
            /sessions/*<sid>*                   | details for session *<sid>*
            /sessions/*<sid>*/move              | move session *<sid>* to a different project
            /sessions/*<sid>*/acquisitions      | list acquisitions for session *<sid>*
            [(/acquisitions/schema)]            | schema for single acquisition
            /acquisitions/*<aid>*               | details for acquisition *<aid>*
            [(/collections)]                    | list of collections
            [(/collections/schema)]             | schema for single collection
            /collections/*<cid>*                | details for collection *<cid>*
            /collections/*<cid>*/sessions       | list of sessions for collection *<cid>*
            /collections/*<cid>*/acquisitions   | list of acquisitions for collection *<cid>*
            [(/schema/group)]                   | group schema
            [(/schema/user)]                    | user schema
            """

        if self.debug and self.uid:
            resources = re.sub(r'\[\((.*)\)\]', r'[\1](/api\1?user=%s&root=%r)' % (self.uid, self.superuser_request), resources)
            resources = re.sub(r'(\(.*)\*<uid>\*(.*\))', r'\1%s\2' % self.uid, resources)
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
        if self.debug and not self.get_param('user'):
            self.response.write('<form name="username" action="" method="get">\n')
            self.response.write('Username: <input type="text" name="user">\n')
            self.response.write('Root: <input type="checkbox" name="root" value="1">\n')
            self.response.write('<input type="submit" value="Generate Custom Links">\n')
            self.response.write('</form>\n')
        self.response.write(markdown.markdown(resources, ['extra']))
        self.response.write('</body>\n')
        self.response.write('</html>\n')

    def reaper(self):
        """Receive a sortable reaper upload."""
        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            try:
                file_store = files.FileStore(self.request, tempdir_path)
            except files.FileStoreException as e:
                self.abort(400, str(e))
            now = datetime.datetime.now()
            fileinfo = dict(
                name=file_store.filename,
                created=now,
                modified=now,
                size=file_store.size,
                hash=file_store.hash,
                tags=file_store.tags,
                metadata=file_store.metadata
            )
            container = reaperutil.create_container_hierarchy(file_store.metadata)
            f = container.find(file_store.filename)
            target_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
            if not f:
                file_store.move_file(target_path)
                container.add_file(fileinfo)
                rules.create_jobs(config.db, container.acquisition, 'acquisition', fileinfo)
            elif not file_store.identical(util.path_from_hash(fileinfo['hash']), f['hash']):
                file_store.move_file(target_path)
                container.update_file(fileinfo)
                rules.create_jobs(config.db, container.acquisition, 'acquisition', fileinfo)
            throughput = file_store.size / file_store.duration.total_seconds()
            log.info('Received    %s [%s, %s/s] from %s' % (file_store.filename, util.hrsize(file_store.size), util.hrsize(throughput), self.request.client_addr))

    def engine(self):
        """
        URL format: api/engine?level=<container_type>&id=<container_id>

        It expects a multipart/form-data request with a "metadata" field (json valid against api/schemas/input/enginemetadata)
        and 0 or more file fields with a non null filename property (filename is null for the "metadata").
        """
        level = self.get_param('level')
        if level != 'acquisition':
            self.abort(404, 'engine uploads are supported only at the acquisition level')
        acquisition_id = self.get_param('id')
        if not acquisition_id:
            self.abort(404, 'container id is required')
        else:
            acquisition_id = bson.ObjectId(acquisition_id)
        if not self.superuser_request:
            self.abort(402, 'uploads must be from an authorized drone')
        with tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path')) as tempdir_path:
            try:
                file_store = files.MultiFileStore(self.request, tempdir_path)
            except files.FileStoreException as e:
                self.abort(400, str(e))
            if not file_store.metadata:
                self.abort(400, 'metadata is missing')
            metadata_validator = validators.payload_from_schema_file(self, 'enginemetadata.json')
            metadata_validator(file_store.metadata, 'POST')
            file_infos = file_store.metadata['acquisition'].pop('files', [])
            try:
                acquisition_obj = reaperutil.update_container_hierarchy(file_store.metadata, acquisition_id, level)
            except APIStorageException as e:
                self.abort(400, e.message)
            # move the files before updating the database
            for name, fileinfo in file_store.files.items():
                path = fileinfo['path']
                target_path = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash(fileinfo['hash']))
                files.move_file(path, target_path)
            # merge infos from the actual file and from the metadata
            merged_infos = self._merge_fileinfos(file_store.files, file_infos)
            # update the fileinfo in mongo if a file already exists
            for f in acquisition_obj['files']:
                fileinfo = merged_infos.get(f['name'])
                if fileinfo:
                    fileinfo.pop('path', None)
                    acquisition_obj = reaperutil.update_fileinfo('acquisitions', acquisition_obj['_id'], fileinfo)
                    fileinfo['existing'] = True
            # create the missing fileinfo in mongo
            for name, fileinfo in merged_infos.items():
                # if the file exists we don't need to create it
                # skip update fileinfo for files that doesn't have a path
                if not fileinfo.get('existing') and fileinfo.get('path'):
                    del fileinfo['path']
                    acquisition_obj = reaperutil.add_fileinfo('acquisitions', acquisition_obj['_id'], fileinfo)

            for f in acquisition_obj['files']:
                if f['name'] in file_store.files:
                    file_ = {
                        'name': f['name'],
                        'hash': f['hash'],
                        'type': f.get('type'),
                        'measurements': f.get('measurements', [])
                    }
                    rules.create_jobs(config.db, acquisition_obj, 'acquisition', file_)
            return [{'name': k, 'hash': v['hash'], 'size': v['size']} for k, v in merged_infos.items()]

    def _merge_fileinfos(self, hard_infos, infos):
        """it takes a dictionary of "hard_infos" (file size, hash)
        merging them with infos derived from a list of infos on the same or on other files
        """
        new_infos = copy.deepcopy(hard_infos)
        for info in infos:
            new_infos[info['name']] = new_infos.get(info['name'], {})
            new_infos[info['name']].update(info)
        return new_infos

    def _preflight_archivestream(self, req_spec, snapshot=False):
        session_cont_name = 'session_snapshots' if snapshot else 'sessions'
        acquisition_cont_name = 'acquisition_snapshots' if snapshot else 'acquisitions'
        project_cont_name = 'project_snapshots' if snapshot else 'projects'
        data_path = config.get_item('persistent', 'data_path')
        arc_prefix = 'sdm'
        file_cnt = 0
        total_size = 0
        targets = []
        # FIXME: check permissions of everything
        used_subpaths = {}
        for item in req_spec['nodes']:
            item_id = bson.ObjectId(item['_id'])
            if item['level'] == 'project':
                project = config.db[project_cont_name].find_one({'_id': item_id}, ['group', 'label', 'files'])
                prefix = '/'.join([arc_prefix, project['group'], project['label']])
                total_size, file_cnt = _append_targets(targets, project, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
                sessions = config.db[session_cont_name].find({'project': item_id}, ['label', 'files', 'uid', 'timestamp', 'timezone'])
                session_dict = {session['_id']: session for session in sessions}
                acquisitions = config.db[acquisition_cont_name].find({'session': {'$in': session_dict.keys()}}, ['label', 'files', 'session', 'uid', 'timestamp', 'timezone'])
                session_prefixes = {}
                for session in session_dict.itervalues():
                    session_prefix = prefix + '/' + self._path_from_container(session, used_subpaths, project['_id'])
                    session_prefixes[session['_id']] = session_prefix
                    total_size, file_cnt = _append_targets(targets, session, session_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
                for acq in acquisitions:
                    session = session_dict[acq['session']]
                    acq_prefix = session_prefixes[session['_id']] + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                    total_size, file_cnt = _append_targets(targets, acq, acq_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
            elif item['level'] == 'session':
                session = config.db[session_cont_name].find_one({'_id': item_id}, ['project', 'label', 'files', 'uid', 'timestamp', 'timezone'])
                project = config.db[project_cont_name].find_one({'_id': session['project']}, ['group', 'label'])
                prefix = project['group'] + '/' + project['label'] + '/' + self._path_from_container(session, used_subpaths, project['_id'])
                total_size, file_cnt = _append_targets(targets, session, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
                acquisitions = config.db[acquisition_cont_name].find({'session': item_id}, ['label', 'files', 'uid', 'timestamp', 'timezone'])
                for acq in acquisitions:
                    acq_prefix = prefix + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                    total_size, file_cnt = _append_targets(targets, acq, acq_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
            elif item['level'] == 'acquisition':
                acq = config.db[acquisition_cont_name].find_one({'_id': item_id}, ['session', 'label', 'files', 'uid', 'timestamp', 'timezone'])
                session = config.db[session_cont_name].find_one({'_id': acq['session']}, ['project', 'label', 'uid', 'timestamp', 'timezone'])
                project = config.db[project_cont_name].find_one({'_id': session['project']}, ['group', 'label'])
                prefix = project['group'] + '/' + project['label'] + '/' + self._path_from_container(session, used_subpaths, project['_id']) + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                total_size, file_cnt = _append_targets(targets, acq, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
        log.debug(json.dumps(targets, sort_keys=True, indent=4, separators=(',', ': ')))
        filename = 'sdm_' + datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.tar'
        ticket = util.download_ticket(self.request.client_addr, 'batch', targets, filename, total_size)
        config.db.downloads.insert_one(ticket)
        return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size}

    def _path_from_container(self, container, used_subpaths, parent_id):
        def _find_new_path(path, list_used_subpaths):
            """from the input path finds a path that hasn't been used"""
            if path not in list_used_subpaths:
                return path
            i = 0
            while True:
                modified_path = path + '_' + str(i)
                if modified_path not in list_used_subpaths:
                    return modified_path
        path = None
        if not path and container.get('label'):
            path = container['label']
        if not path and container.get('timestamp'):
            timezone = container.get('timezone')
            if timezone:
                path = pytz.timezone('UTC').localize(container['timestamp']).astimezone(pytz.timezone(timezone)).strftime('%Y%m%d_%H%M')
            else:
                path = container['timestamp'].strftime('%Y%m%d_%H%M')
        if not path and container.get('uid'):
            path = container['uid']
        if not path:
            path = 'untitled'
        path = _find_new_path(path, used_subpaths.get(parent_id, []))
        used_subpaths[parent_id] = used_subpaths.get(parent_id, []) + [path]
        return path

    def _preflight_archivestream_bids(self, req_spec, snapshot=False):
        session_cont_name = 'session_snapshots' if snapshot else 'sessions'
        acquisition_cont_name = 'acquisition_snapshots' if snapshot else 'acquisitions'
        project_cont_name = 'project_snapshots' if snapshot else 'projects'
        data_path = config.get_item('persistent', 'data_path')
        file_cnt = 0
        total_size = 0
        targets = []
        # FIXME: check permissions of everything
        projects = []
        prefix = 'untitled'
        used_subpaths = {}
        if len(req_spec['nodes']) != 1:
            self.abort(400, 'bids downloads are limited to single dataset downloads')
        for item in req_spec['nodes']:
            item_id = bson.ObjectId(item['_id'])
            if item['level'] == 'project':
                project = config.db[project_cont_name].find_one({'_id': item_id}, ['group', 'label', 'files', 'notes'])
                projects.append(item_id)
                prefix = project['label']
                total_size, file_cnt = _append_targets(targets, project, prefix, total_size,
                                                       file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
                ses_or_subj_list = config.db[session_cont_name].find({'project': item_id}, ['_id', 'label', 'files', 'subject.code', 'subject_code', 'uid', 'timestamp', 'timezone'])
                subject_prefixes = {
                    'missing_subject': prefix + '/missing_subject'
                }
                sessions = {}
                for ses_or_subj in ses_or_subj_list:
                    log.error(ses_or_subj)
                    subj_code = ses_or_subj.get('subject', {}).get('code') or ses_or_subj.get('subject_code')
                    if subj_code == 'subject':
                        subject_prefix = prefix + '/' + self._path_from_container(ses_or_subj, used_subpaths, project['_id'])
                        total_size, file_cnt = _append_targets(targets, ses_or_subj, subject_prefix, total_size,
                                                               file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
                        subject_prefixes[str(ses_or_subj.get('_id'))] = subject_prefix
                    elif subj_code:
                        sessions[subj_code] = sessions.get(subj_code, []) + [ses_or_subj]
                    else:
                        sessions['missing_subject'] = sessions.get('missing_subject', []) + [ses_or_subj]
                for subj_code, ses_list in sessions.items():
                    subject_prefix = subject_prefixes.get(subj_code)
                    if not subject_prefix:
                        continue
                    for session in ses_list:
                        session_prefix = subject_prefix + '/' + self._path_from_container(session, used_subpaths, subj_code)
                        total_size, file_cnt = _append_targets(targets, session, session_prefix, total_size,
                                                               file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
                        acquisitions = config.db[acquisition_cont_name].find({'session': session['_id']}, ['label', 'files', 'uid', 'timestamp', 'timezone'])
                        for acq in acquisitions:
                            acq_prefix = session_prefix + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                            total_size, file_cnt = _append_targets(targets, acq, acq_prefix, total_size,
                                                                   file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))
        log.debug(json.dumps(targets, sort_keys=True, indent=4, separators=(',', ': ')))
        filename = prefix + '_' + datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.tar'
        ticket = util.download_ticket(self.request.client_addr, 'batch', targets, filename, total_size, projects)
        config.db.downloads.insert_one(ticket)
        return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size}

    def _archivestream(self, ticket):
        BLOCKSIZE = 512
        CHUNKSIZE = 2**20  # stream files in 1MB chunks
        stream = cStringIO.StringIO()
        with tarfile.open(mode='w|', fileobj=stream) as archive:
            for filepath, arcpath, _ in ticket['target']:
                yield archive.gettarinfo(filepath, arcpath).tobuf()
                with open(filepath, 'rb') as fd:
                    for chunk in iter(lambda: fd.read(CHUNKSIZE), ''):
                        yield chunk
                    if len(chunk) % BLOCKSIZE != 0:
                        yield (BLOCKSIZE - (len(chunk) % BLOCKSIZE)) * b'\0'
        yield stream.getvalue() # get tar stream trailer
        stream.close()

    def _symlinkarchivestream(self, ticket, data_path):
        for filepath, arcpath, _ in ticket['target']:
            t = tarfile.TarInfo(name=arcpath)
            t.type = tarfile.SYMTYPE
            t.linkname = os.path.relpath(filepath, data_path)
            yield t.tobuf()
        stream = cStringIO.StringIO()
        with tarfile.open(mode='w|', fileobj=stream) as archive:
            pass
        yield stream.getvalue() # get tar stream trailer
        stream.close()

    def download_snapshot(self):
        return self.download(snapshot=True)

    def download(self, snapshot=False):
        """
        In downloads we use filters in the payload to exclude/include files.
        To pass a single filter, each of its conditions should be satisfied.
        If a file pass at least one filter, it is included in the targets.
        For example:

        download_payload = {
            'optional': True,
            'nodes': [{'level':'project', '_id':project_id}],
            'filters':[{
                'tags':{'+':['incomplete']}
            },
            {
                'types':{'-':['dicom']}
            }]
        }
        will download files with tag 'incomplete' OR type different from 'dicom'

        download_payload = {
            'optional': True,
            'nodes': [{'level':'project', '_id':project_id}],
            'filters':[{
                'tags':{'+':['incomplete']},
                'types':{'+':['dicom']}
            }]
        }
        will download only files with tag 'incomplete' AND type different from 'dicom'
        """
        ticket_id = self.get_param('ticket')
        if ticket_id:
            ticket = config.db.downloads.find_one({'_id': ticket_id})
            if not ticket:
                self.abort(404, 'no such ticket')
            if ticket['ip'] != self.request.client_addr:
                self.abort(400, 'ticket not for this source IP')
            if self.get_param('symlinks'):
                self.response.app_iter = self._symlinkarchivestream(ticket, config.get_item('persistent', 'data_path'))
            else:
                self.response.app_iter = self._archivestream(ticket)
            self.response.headers['Content-Type'] = 'application/octet-stream'
            self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(ticket['filename'])
            for project_id in ticket['projects']:
                if snapshot:
                    config.db.project_snapshots.update_one({'_id': project_id}, {'$inc': {'counter': 1}})
                else:
                    config.db.projects.update_one({'_id': project_id}, {'$inc': {'counter': 1}})
        else:
            req_spec = self.request.json_body
            validator = validators.payload_from_schema_file(self, 'download.json')
            validator(req_spec, 'POST')
            log.debug(json.dumps(req_spec, sort_keys=True, indent=4, separators=(',', ': ')))
            if self.get_param('format') == 'bids':
                return self._preflight_archivestream_bids(req_spec, snapshot=snapshot)
            else:
                return self._preflight_archivestream(req_spec, snapshot=snapshot)

    def sites(self):
        """Return local and remote sites."""
        projection = ['name', 'onload']
        # TODO onload for local is true
        site_id = config.get_item('site', 'id')
        if self.public_request or self.is_true('all'):
            sites = list(config.db.sites.find(None, projection))
        else:
            # TODO onload based on user prefs
            remotes = (config.db.users.find_one({'_id': self.uid}, ['remotes']) or {}).get('remotes', [])
            remote_ids = [r['_id'] for r in remotes] + [site_id]
            sites = list(config.db.sites.find({'_id': {'$in': remote_ids}}, projection))
        for s in sites:  # TODO: this for loop will eventually move to public case
            if s['_id'] == site_id:
                s['onload'] = True
                break
        return sites

    def register(self):
        if not config.get_item('site', 'registered'):
            self.abort(400, 'Site not registered with central')
        if not config.get_item('site', 'ssl_cert'):
            self.abort(400, 'SSL cert not configured')
        if not config.get_item('site', 'central_url'):
            self.abort(400, 'Central URL not configured')
        if not centralclient.update(config.db, config.get_item('site', 'ssl_cert'), config.get_item('site', 'central_url')):
            centralclient.fail_count += 1
        else:
            centralclient.fail_count = 0
        if centralclient.fail_count == 3:
            log.warning('scitran central unreachable, purging all remotes info')
            centralclient.clean_remotes(mongo.db)
