import bson
import json
import pytz
import os.path
import tarfile
import datetime
import cStringIO

from .web import base
from .web.request import AccessType
from . import config
from . import util
from . import validators
import os
from .dao.containerutil import pluralize

log = config.log


def _filter_check(property_filter, property_values):
    minus = set(property_filter.get('-', []))
    plus = set(property_filter.get('+', []))
    if not minus.isdisjoint(property_values):
        return False
    if plus and plus.isdisjoint(property_values):
        return False
    return True


class Download(base.RequestHandler):

    def _append_targets(self, targets, cont_name, container, prefix, total_size, total_cnt, optional, data_path, filters):
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
                    targets.append((filepath, prefix + '/' + f['name'], cont_name, str(container.get('_id')),f['size']))
                    total_size += f['size']
                    total_cnt += 1
        return total_size, total_cnt

    def _bulk_preflight_archivestream(self, file_refs):
        data_path = config.get_item('persistent', 'data_path')
        arc_prefix =  self.get_param('prefix', 'scitran')
        file_cnt = 0
        total_size = 0
        targets = []

        for fref in file_refs:

            cont_id     = fref.get('container_id', '')
            filename    = fref.get('filename', '')
            cont_name   = fref.get('container_name','')

            if cont_name not in ['project', 'session', 'acquisition', 'analysis']:
                self.abort(400, 'Bulk download only supports files in projects, sessions, analyses and acquisitions')
            cont_name   = pluralize(fref.get('container_name',''))


            file_obj = None
            try:
                # Try to find the file reference in the database (filtering on user permissions)
                bid = bson.ObjectId(cont_id)
                query = {'_id': bid}
                if not self.superuser_request:
                    query['permissions._id'] = self.uid
                file_obj = config.db[cont_name].find_one(
                    query,
                    {'files': { '$elemMatch': {
                        'name': filename
                    }}
                })['files'][0]
            except Exception: # pylint: disable=broad-except
                # self.abort(404, 'File {} on Container {} {} not found'.format(filename, cont_name, cont_id))
                # silently skip missing files/files user does not have access to
                continue

            filepath = os.path.join(data_path, util.path_from_hash(file_obj['hash']))
            if os.path.exists(filepath): # silently skip missing files
                targets.append((filepath, cont_name+'/'+cont_id+'/'+file_obj['name'], cont_name, cont_id, file_obj['size']))
                total_size += file_obj['size']
                file_cnt += 1

        if len(targets) > 0:
            filename = arc_prefix + '_ '+datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.tar'
            ticket = util.download_ticket(self.request.client_addr, 'batch', targets, filename, total_size)
            config.db.downloads.insert_one(ticket)
            return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size}
        else:
            self.abort(404, 'No files requested could be found')


    def _preflight_archivestream(self, req_spec, collection=None):
        data_path = config.get_item('persistent', 'data_path')
        arc_prefix = self.get_param('prefix', 'scitran')
        file_cnt = 0
        total_size = 0
        targets = []
        filename = None

        used_subpaths = {}
        base_query = {}
        if not self.superuser_request:
            base_query['permissions._id'] = self.uid

        for item in req_spec['nodes']:

            item_id = bson.ObjectId(item['_id'])
            base_query['_id'] = item_id

            if item['level'] == 'project':
                project = config.db.projects.find_one(base_query, ['group', 'label', 'files'])
                if not project:
                    # silently skip missing objects/objects user does not have access to
                    continue

                prefix = '/'.join([arc_prefix, project['group'], project['label']])
                total_size, file_cnt = self._append_targets(targets, 'projects', project, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

                sessions = config.db.sessions.find({'project': item_id}, ['label', 'files', 'uid', 'timestamp', 'timezone', 'subject'])
                session_dict = {session['_id']: session for session in sessions}
                acquisitions = config.db.acquisitions.find({'session': {'$in': session_dict.keys()}}, ['label', 'files', 'session', 'uid', 'timestamp', 'timezone'])
                session_prefixes = {}

                subject_dict = {}
                subject_prefixes = {}
                for session in session_dict.itervalues():
                    if session.get('subject'):
                        code = session['subject'].get('code', 'unknown_subject')
                        # This is bad and we should try to combine these somehow,
                        # or at least make sure we get all the files
                        subject_dict[code] = session['subject']

                for code, subject in subject_dict.iteritems():
                    subject_prefix = prefix + '/' + self._path_from_container(subject, used_subpaths, project['_id'])
                    subject_prefixes[code] = subject_prefix
                    total_size, file_cnt = self._append_targets(targets, 'subjects', subject, subject_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

                for session in session_dict.itervalues():
                    subject_code = session['subject'].get('code', 'unknown_subject')
                    subject = subject_dict[subject_code]
                    session_prefix = subject_prefixes[subject_code] + '/' + self._path_from_container(session, used_subpaths, subject_code)
                    session_prefixes[session['_id']] = session_prefix
                    total_size, file_cnt = self._append_targets(targets, 'sessions', session, session_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

                for acq in acquisitions:
                    session = session_dict[acq['session']]
                    acq_prefix = session_prefixes[session['_id']] + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                    total_size, file_cnt = self._append_targets(targets, 'acquisitions', acq, acq_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))


            elif item['level'] == 'session':
                session = config.db.sessions.find_one(base_query, ['project', 'label', 'files', 'uid', 'timestamp', 'timezone', 'subject'])
                if not session:
                    # silently skip missing objects/objects user does not have access to
                    continue

                project = config.db.projects.find_one({'_id': session['project']}, ['group', 'label'])
                subject = session.get('subject', {'code': 'unknown_subject'})
                if not subject.get('code'):
                    subject['code'] = 'unknown_subject'
                prefix = project['group'] + '/' + project['label'] + '/' + self._path_from_container(subject, used_subpaths, project['_id']) + '/' + self._path_from_container(session, used_subpaths, project['_id'])
                total_size, file_cnt = self._append_targets(targets, 'sessions', session, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

                # If the param `collection` holding a collection id is not None, filter out acquisitions that are not in the collection
                a_query = {'session': item_id}
                if collection: # cover 100
                    a_query['collections'] = bson.ObjectId(collection)
                acquisitions = config.db.acquisitions.find(a_query, ['label', 'files', 'uid', 'timestamp', 'timezone'])

                for acq in acquisitions:
                    acq_prefix = prefix + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                    total_size, file_cnt = self._append_targets(targets, 'acquisitions', acq, acq_prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

            elif item['level'] == 'acquisition':
                acq = config.db.acquisitions.find_one(base_query, ['session', 'label', 'files', 'uid', 'timestamp', 'timezone'])
                if not acq:
                    # silently skip missing objects/objects user does not have access to
                    continue

                session = config.db.sessions.find_one({'_id': acq['session']}, ['project', 'label', 'uid', 'timestamp', 'timezone', 'subject'])
                subject = session.get('subject', {'code': 'unknown_subject'})
                if not subject.get('code'):
                    subject['code'] = 'unknown_subject'

                project = config.db.projects.find_one({'_id': session['project']}, ['group', 'label'])
                prefix = project['group'] + '/' + project['label'] + '/' + self._path_from_container(subject, used_subpaths, project['_id']) + '/' + self._path_from_container(session, used_subpaths, project['_id']) + '/' + self._path_from_container(acq, used_subpaths, session['_id'])
                total_size, file_cnt = self._append_targets(targets, 'acquisitions', acq, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

            elif item['level'] == 'analysis':
                analysis = config.db.analyses.find_one(base_query, ['parent', 'label', 'files', 'uid', 'timestamp'])
                if not analysis: # cover 100
                    # silently skip missing objects/objects user does not have access to
                    continue
                prefix = self._path_from_container(analysis, used_subpaths, util.sanitize_string_to_filename(analysis['label']))
                filename = 'analysis_' + util.sanitize_string_to_filename(analysis['label']) + '.tar'
                total_size, file_cnt = self._append_targets(targets, 'analyses', analysis, prefix, total_size, file_cnt, req_spec['optional'], data_path, req_spec.get('filters'))

        if len(targets) > 0:
            log.debug(json.dumps(targets, sort_keys=True, indent=4, separators=(',', ': ')))
            if not filename:
                filename = arc_prefix + '_' + datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.tar'
            ticket = util.download_ticket(self.request.client_addr, 'batch', targets, filename, total_size)
            config.db.downloads.insert_one(ticket)
            return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size, 'filename': filename}
        else:
            self.abort(404, 'No requested containers could be found')

    def _path_from_container(self, container, used_subpaths, parent_id):
        def _find_new_path(path, list_used_subpaths):
            """from the input path finds a path that hasn't been used"""
            path = str(path).replace('/', '_')
            if path not in list_used_subpaths:
                return path
            i = 0
            while True:
                modified_path = path + '_' + str(i)
                if modified_path not in list_used_subpaths:
                    return modified_path
                i += 1
        path = None
        if not path and container.get('label'):
            path = container['label']
        if not path and container.get('timestamp'): # cover 100
            timezone = container.get('timezone')
            if timezone:
                path = pytz.timezone('UTC').localize(container['timestamp']).astimezone(pytz.timezone(timezone)).strftime('%Y%m%d_%H%M')
            else:
                path = container['timestamp'].strftime('%Y%m%d_%H%M')
        if not path and container.get('uid'): # cover 100
            path = container['uid']
        if not path and container.get('code'):
            path = container['code']
        if not path:
            path = 'untitled'
        path = _find_new_path(path, used_subpaths.get(parent_id, []))
        used_subpaths[parent_id] = used_subpaths.get(parent_id, []) + [path]
        return path

    def archivestream(self, ticket):
        BLOCKSIZE = 512
        CHUNKSIZE = 2**20  # stream files in 1MB chunks
        stream = cStringIO.StringIO()
        with tarfile.open(mode='w|', fileobj=stream) as archive:
            for filepath, arcpath, cont_name, cont_id, _ in ticket['target']:
                yield archive.gettarinfo(filepath, arcpath).tobuf()
                with open(filepath, 'rb') as fd:
                    chunk = ''
                    for chunk in iter(lambda: fd.read(CHUNKSIZE), ''): # pylint: disable=cell-var-from-loop
                        yield chunk
                    if len(chunk) % BLOCKSIZE != 0:
                        yield (BLOCKSIZE - (len(chunk) % BLOCKSIZE)) * b'\0'
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cont_id, multifile=True) # log download
        yield stream.getvalue() # get tar stream trailer
        stream.close()

    def symlinkarchivestream(self, ticket, data_path):
        for filepath, arcpath, cont_name, cont_id, _ in ticket['target']:
            t = tarfile.TarInfo(name=arcpath)
            t.type = tarfile.SYMTYPE
            t.linkname = os.path.relpath(filepath, data_path)
            yield t.tobuf()
            self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cont_id, multifile=True) # log download
        stream = cStringIO.StringIO()
        with tarfile.open(mode='w|', fileobj=stream) as _:
            pass
        yield stream.getvalue() # get tar stream trailer
        stream.close()

    def download(self):
        """Download files or create a download ticket"""
        ticket_id = self.get_param('ticket')
        if ticket_id:
            ticket = config.db.downloads.find_one({'_id': ticket_id})
            if not ticket:
                self.abort(404, 'no such ticket')
            if ticket['ip'] != self.request.client_addr:
                self.abort(400, 'ticket not for this source IP')
            if self.get_param('symlinks'):
                self.response.app_iter = self.symlinkarchivestream(ticket, config.get_item('persistent', 'data_path'))
            else:
                self.response.app_iter = self.archivestream(ticket)
            self.response.headers['Content-Type'] = 'application/octet-stream'
            self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(ticket['filename'])
            for project_id in ticket['projects']: # cover 100
                config.db.projects.update_one({'_id': project_id}, {'$inc': {'counter': 1}})
        else:
            req_spec = self.request.json_body

            if self.is_true('bulk'):
                return self._bulk_preflight_archivestream(req_spec.get('files', []))
            else:
                payload_schema_uri = validators.schema_uri('input', 'download.json')
                validator = validators.from_schema_path(payload_schema_uri)
                validator(req_spec, 'POST')
                log.debug(json.dumps(req_spec, sort_keys=True, indent=4, separators=(',', ': ')))

                return self._preflight_archivestream(req_spec, collection=self.get_param('collection'))
