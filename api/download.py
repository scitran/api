import os
import bson
import pytz
import tarfile
import datetime
import cStringIO

import fs.path
import fs.errors

from .web import base
from .web.request import AccessType
from . import config, files, util, validators
from .dao.containerutil import pluralize

log = config.log

BYTES_IN_MEGABYTE = float(1<<20)

def _filter_check(property_filter, property_values):
    minus = set(property_filter.get('-', []) + property_filter.get('minus', []))
    plus = set(property_filter.get('+', []) + property_filter.get('plus', []))
    if "null" in plus and not property_values:
        return True
    if "null" in minus and property_values:
        return False
    elif not minus.isdisjoint(property_values):
        return False
    if plus and plus.isdisjoint(property_values):
        return False
    return True


class Download(base.RequestHandler):

    def _append_targets(self, targets, cont_name, container, prefix, total_size, total_cnt, filters):
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

            file_path, _ = files.get_valid_file(f)
            if file_path:  # silently skip missing files
                if cont_name == 'analyses':
                    targets.append((file_path, prefix + '/' + ('input' if f.get('input') else 'output') + '/' + f['name'], cont_name, str(container.get('_id')), f['size']))
                else:
                    targets.append((file_path, prefix + '/' + f['name'], cont_name, str(container.get('_id')), f['size']))
                total_size += f['size']
                total_cnt += 1
            else:
                log.warn("Expected {} to exist but it is missing. File will be skipped in download.".format(file_path))
        return total_size, total_cnt

    def _bulk_preflight_archivestream(self, file_refs):
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
                log.warn("Expected file {} on Container {} {} to exist but it is missing. File will be skipped in download.".format(filename, cont_name, cont_id))
                continue

            file_path, _ = files.get_valid_file(file_obj)
            if file_path:  # silently skip missing files
                targets.append((file_path, cont_name+'/'+cont_id+'/'+file_obj['name'], cont_name, cont_id, file_obj['size']))
                total_size += file_obj['size']
                file_cnt += 1

        if len(targets) > 0:
            filename = arc_prefix + '_ '+datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.tar'
            ticket = util.download_ticket(self.request.client_addr, self.origin, 'batch', targets, filename, total_size)
            config.db.downloads.insert_one(ticket)
            return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size}
        else:
            self.abort(404, 'No files requested could be found')


    def _preflight_archivestream(self, req_spec, collection=None):
        arc_prefix = self.get_param('prefix', 'scitran')
        file_cnt = 0
        total_size = 0
        targets = []
        filename = None

        ids_of_paths = {}
        base_query = {'deleted': {'$exists': False}}
        if not self.superuser_request:
            base_query['permissions._id'] = self.uid

        for item in req_spec['nodes']:

            item_id = bson.ObjectId(item['_id'])
            base_query['_id'] = item_id

            if item['level'] == 'project':
                project = config.db.projects.find_one(base_query, ['group', 'label', 'files'])
                if not project:
                    # silently(while logging it) skip missing objects/objects user does not have access to
                    log.warn("Expected project {} to exist but it is missing. Node will be skipped".format(item_id))
                    continue

                prefix = '/'.join([arc_prefix, project['group'], project['label']])
                total_size, file_cnt = self._append_targets(targets, 'projects', project, prefix, total_size, file_cnt, req_spec.get('filters'))

                sessions = config.db.sessions.find({'project': item_id, 'deleted': {'$exists': False}}, ['label', 'files', 'uid', 'timestamp', 'timezone', 'subject'])
                session_dict = {session['_id']: session for session in sessions}
                acquisitions = config.db.acquisitions.find({'session': {'$in': session_dict.keys()}, 'deleted': {'$exists': False}}, ['label', 'files', 'session', 'uid', 'timestamp', 'timezone'])
                session_prefixes = {}

                subject_dict = {}
                subject_prefixes = {}
                for session in session_dict.itervalues():
                    if session.get('subject'):
                        subject = session.get('subject', {'code': 'unknown_subject'})
                        code = subject.get('code')
                        if code is None:
                            code = 'unknown_subject'
                            subject['code'] = code
                        subject_dict[code] = subject

                for code, subject in subject_dict.iteritems():
                    subject_prefix = self._path_from_container(prefix, subject, ids_of_paths, code)
                    subject_prefixes[code] = subject_prefix
                    total_size, file_cnt = self._append_targets(targets, 'subjects', subject, subject_prefix, total_size, file_cnt, req_spec.get('filters'))

                for session in session_dict.itervalues():
                    subject_code = session['subject'].get('code', 'unknown_subject')
                    subject = subject_dict[subject_code]
                    session_prefix = self._path_from_container(subject_prefixes[subject_code], session, ids_of_paths, session["_id"])
                    session_prefixes[session['_id']] = session_prefix
                    total_size, file_cnt = self._append_targets(targets, 'sessions', session, session_prefix, total_size, file_cnt, req_spec.get('filters'))

                for acq in acquisitions:
                    session = session_dict[acq['session']]
                    acq_prefix = self._path_from_container(session_prefixes[session['_id']], acq, ids_of_paths, acq['_id'])
                    total_size, file_cnt = self._append_targets(targets, 'acquisitions', acq, acq_prefix, total_size, file_cnt, req_spec.get('filters'))


            elif item['level'] == 'session':
                session = config.db.sessions.find_one(base_query, ['project', 'label', 'files', 'uid', 'timestamp', 'timezone', 'subject'])
                if not session:
                    # silently(while logging it) skip missing objects/objects user does not have access to
                    log.warn("Expected session {} to exist but it is missing. Node will be skipped".format(item_id))
                    continue

                project = config.db.projects.find_one({'_id': session['project']}, ['group', 'label'])
                subject = session.get('subject', {'code': 'unknown_subject'})
                if not subject.get('code'):
                    subject['code'] = 'unknown_subject'
                prefix = self._path_from_container(self._path_from_container(project['group'] + '/' + project['label'], subject, ids_of_paths, subject["code"]), session, ids_of_paths, session['_id'])
                total_size, file_cnt = self._append_targets(targets, 'sessions', session, prefix, total_size, file_cnt, req_spec.get('filters'))

                # If the param `collection` holding a collection id is not None, filter out acquisitions that are not in the collection
                a_query = {'session': item_id, 'deleted': {'$exists': False}}
                if collection:
                    a_query['collections'] = bson.ObjectId(collection)
                acquisitions = config.db.acquisitions.find(a_query, ['label', 'files', 'uid', 'timestamp', 'timezone'])

                for acq in acquisitions:
                    acq_prefix = self._path_from_container(prefix, acq, ids_of_paths, acq['_id'])
                    total_size, file_cnt = self._append_targets(targets, 'acquisitions', acq, acq_prefix, total_size, file_cnt, req_spec.get('filters'))

            elif item['level'] == 'acquisition':
                acq = config.db.acquisitions.find_one(base_query, ['session', 'label', 'files', 'uid', 'timestamp', 'timezone'])
                if not acq:
                    # silently(while logging it) skip missing objects/objects user does not have access to
                    log.warn("Expected acquisition {} to exist but it is missing. Node will be skipped".format(item_id))
                    continue

                session = config.db.sessions.find_one({'_id': acq['session']}, ['project', 'label', 'uid', 'timestamp', 'timezone', 'subject'])
                subject = session.get('subject', {'code': 'unknown_subject'})
                if not subject.get('code'):
                    subject['code'] = 'unknown_subject'

                project = config.db.projects.find_one({'_id': session['project']}, ['group', 'label'])
                prefix = self._path_from_container(self._path_from_container(self._path_from_container(project['group'] + '/' + project['label'], subject, ids_of_paths, subject['code']), session, ids_of_paths, session["_id"]), acq, ids_of_paths, acq['_id'])
                total_size, file_cnt = self._append_targets(targets, 'acquisitions', acq, prefix, total_size, file_cnt, req_spec.get('filters'))

            elif item['level'] == 'analysis':
                analysis = config.db.analyses.find_one(base_query, ['parent', 'label', 'files', 'uid', 'timestamp'])
                if not analysis:
                    # silently(while logging it) skip missing objects/objects user does not have access to
                    log.warn("Expected anaylysis {} to exist but it is missing. Node will be skipped".format(item_id))
                    continue
                prefix = self._path_from_container("", analysis, ids_of_paths, util.sanitize_string_to_filename(analysis['label']))
                filename = 'analysis_' + util.sanitize_string_to_filename(analysis['label']) + '.tar'
                total_size, file_cnt = self._append_targets(targets, 'analyses', analysis, prefix, total_size, file_cnt, req_spec.get('filters'))

        if len(targets) > 0:
            if not filename:
                filename = arc_prefix + '_' + datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + '.tar'
            ticket = util.download_ticket(self.request.client_addr, self.origin, 'batch', targets, filename, total_size)
            config.db.downloads.insert_one(ticket)
            return {'ticket': ticket['_id'], 'file_cnt': file_cnt, 'size': total_size, 'filename': filename}
        else:
            self.abort(404, 'No requested containers could be found')

    def _path_from_container(self, prefix, container, ids_of_paths, _id):
        """
        Returns the full path of a container instead of just a subpath, it must be provided with a prefix though
        """
        def _find_new_path(path, ids_of_paths, _id):
            """
            Checks to see if the full path is used
            """
            if _id in ids_of_paths.keys():
                # If the id is already associated with a path, use that instead of modifying it
                return ids_of_paths[_id]
            used_paths = [ids_of_paths[id_] for id_ in ids_of_paths if id_ != _id]
            path = str(path)
            i = 0
            modified_path = path
            while modified_path in used_paths:
                modified_path = path + '_' + str(i)
                i += 1
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
        if not path and container.get('code'):
            path = container['code']
        if not path:
            path = 'untitled'

        path = prefix + '/' + path
        path = _find_new_path(path, ids_of_paths, _id)
        ids_of_paths[_id] = path
        return path

    def archivestream(self, ticket):
        BLOCKSIZE = 512
        CHUNKSIZE = 2**20  # stream files in 1MB chunks
        stream = cStringIO.StringIO()
        with tarfile.open(mode='w|', fileobj=stream) as archive:
            for filepath, arcpath, cont_name, cont_id, _ in ticket['target']:
                file_system = files.get_fs_by_file_path(filepath)
                with file_system.open(filepath, 'rb') as fd:
                    yield archive.gettarinfo(fileobj=fd, arcname=arcpath).tobuf()
                    chunk = ''
                    for chunk in iter(lambda: fd.read(CHUNKSIZE), ''): # pylint: disable=cell-var-from-loop
                        yield chunk
                    if len(chunk) % BLOCKSIZE != 0:
                        yield (BLOCKSIZE - (len(chunk) % BLOCKSIZE)) * b'\0'
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cont_id, filename=os.path.basename(arcpath), multifile=True, origin_override=ticket['origin']) # log download
        yield stream.getvalue() # get tar stream trailer
        stream.close()

    def symlinkarchivestream(self, ticket):
        for filepath, arcpath, cont_name, cont_id, _ in ticket['target']:
            t = tarfile.TarInfo(name=arcpath)
            t.type = tarfile.SYMTYPE
            t.linkname = fs.path.relpath(filepath)
            yield t.tobuf()
            self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cont_id, filename=os.path.basename(arcpath), multifile=True, origin_override=ticket['origin']) # log download
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
                self.response.app_iter = self.symlinkarchivestream(ticket)
            else:
                self.response.app_iter = self.archivestream(ticket)
            self.response.headers['Content-Type'] = 'application/octet-stream'
            self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(ticket['filename'])
        else:

            req_spec = self.request.json_body

            if self.is_true('bulk'):
                return self._bulk_preflight_archivestream(req_spec.get('files', []))
            else:
                payload_schema_uri = validators.schema_uri('input', 'download.json')
                validator = validators.from_schema_path(payload_schema_uri)
                validator(req_spec, 'POST')
                return self._preflight_archivestream(req_spec, collection=self.get_param('collection'))

    def summary(self):
        """Return a summary of what has been/will be downloaded based on a given query"""
        res = {}
        req = self.request.json_body
        cont_query = {
            'projects': {'_id': {'$in':[]}},
            'sessions': {'_id': {'$in':[]}},
            'acquisitions': {'_id': {'$in':[]}},
            'analyses' : {'_id': {'$in':[]}}
        }
        for node in req:
            node['_id'] = bson.ObjectId(node['_id'])
            level = node['level']

            containers = {'projects':0, 'sessions':0, 'acquisitions':0, 'analyses':0}

            if level == 'project':
                # Grab sessions and their ids
                sessions = config.db.sessions.find({'project': node['_id'], 'deleted': {'$exists': False}}, {'_id': 1})
                session_ids = [s['_id'] for s in sessions]
                acquisitions = config.db.acquisitions.find({'session': {'$in': session_ids}, 'deleted': {'$exists': False}}, {'_id': 1})
                acquisition_ids = [a['_id'] for a in acquisitions]

                containers['projects']=1
                containers['sessions']=1
                containers['acquisitions']=1

                # for each type of container below it will have a slightly modified match query
                cont_query.get('projects',{}).get('_id',{}).get('$in').append(node['_id'])
                cont_query['sessions']['_id']['$in'] = cont_query['sessions']['_id']['$in'] + session_ids
                cont_query['acquisitions']['_id']['$in'] = cont_query['acquisitions']['_id']['$in'] + acquisition_ids

            elif level == 'session':
                acquisitions = config.db.acquisitions.find({'session': node['_id'], 'deleted': {'$exists': False}}, {'_id': 1})
                acquisition_ids = [a['_id'] for a in acquisitions]


                # for each type of container below it will have a slightly modified match query
                cont_query.get('sessions',{}).get('_id',{}).get('$in').append(node['_id'])
                cont_query['acquisitions']['_id']['$in'] = cont_query['acquisitions']['_id']['$in'] + acquisition_ids

                containers['sessions']=1
                containers['acquisitions']=1

            elif level == 'acquisition':

                cont_query.get('acquisitions',{}).get('_id',{}).get('$in').append(node['_id'])
                containers['acquisitions']=1

            elif level == 'analysis':
                cont_query.get('analyses',{}).get('_id',{}).get('$in').append(node['_id'])
                containers['analyses'] = 1

            else:
                self.abort(400, "{} not a recognized level".format(level))

            containers = [cont for cont in containers if containers[cont] == 1]

        for cont_name in containers:
            # Aggregate file types
            pipeline = [
                {'$match': cont_query[cont_name]},
                {'$unwind': '$files'},
                {'$project': {'_id': '$_id', 'type': '$files.type','mbs': {'$divide': ['$files.size', BYTES_IN_MEGABYTE]}}},
                {'$group': {
                    '_id': '$type',
                    'count': {'$sum' : 1},
                    'mb_total': {'$sum':'$mbs'}
                }}
            ]

            try:
                result = config.db.command('aggregate', cont_name, pipeline=pipeline)
            except Exception as e: # pylint: disable=broad-except
                log.warning(e)
                self.abort(500, "Failure to load summary")

            if result.get("ok"):
                for doc in result.get("result"):
                    type_ = doc['_id']
                    if res.get(type_):
                        res[type_]['count'] += doc.get('count',0)
                        res[type_]['mb_total'] += doc.get('mb_total',0)
                    else:
                        res[type_] = doc
        return res
