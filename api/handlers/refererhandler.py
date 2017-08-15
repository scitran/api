"""
Module defining RefererHandler and it's subclasses. RefererHandler
generalizes the handling of documents that are not part of the container
hierarchy, are always associated with (referencing) a parent container,
and are stored in their own collection instead of an embedded list on the
container (eg. ListHandler)
"""

import os
import zipfile
import datetime
from abc import ABCMeta, abstractproperty

from .. import config
from .. import upload
from .. import util
from .. import validators
from ..auth import containerauth, always_ok
from ..dao import APIStorageException, containerstorage, noop
from ..web import base
from ..web.request import log_access, AccessType
from .listhandler import FileListHandler


log = config.log


class RefererHandler(base.RequestHandler):
    __metaclass__ = ABCMeta

    storage = abstractproperty()
    payload_schema_file = abstractproperty()
    permchecker = containerauth.default_referer

    @property
    def input_validator(self):
        input_schema_uri = validators.schema_uri('input', self.payload_schema_file)
        input_validator = validators.from_schema_path(input_schema_uri)
        return input_validator

    @property
    def update_validator(self):
        update_schema_uri = validators.schema_uri('input', self.update_payload_schema_file)
        update_validator = validators.from_schema_path(update_schema_uri)
        return update_validator

    def get_permchecker(self, parent_container):
        if self.superuser_request:
            return always_ok
        elif self.public_request: # cover 100
            return containerauth.public_request(self, container=parent_container)
        else:
            # NOTE The handler (self) is passed implicitly
            return self.permchecker(parent_container=parent_container)


class AnalysesHandler(RefererHandler):
    storage = containerstorage.AnalysisStorage()
    payload_schema_file = 'analysis.json'
    update_payload_schema_file = 'analysis-update.json'


    def post(self, cont_name, cid):
        """
        Default behavior:
            Creates an analysis object and uploads supplied input
            and output files.
        When param ``job`` is true:
            Creates an analysis object and job object that reference
            each other via ``job`` and ``destination`` fields. Job based
            analyses are only allowed at the session level.
        """
        parent = self.storage.get_parent(cont_name, cid)
        permchecker = self.get_permchecker(parent)
        permchecker(noop)('POST')

        if self.is_true('job'):
            if cont_name != 'sessions': # cover 100
                self.abort(400, 'Analysis created via a job must be at the session level')

            payload = self.request.json_body
            analysis = payload.get('analysis')
            job = payload.get('job')
            if not analysis or not job:
                self.abort(400, 'JSON body must contain map for "analysis" and "job"')
            self.input_validator(analysis, 'POST')
            result = self.storage.create_job_and_analysis(cont_name, cid, analysis, job, self.origin)
            return {'_id': result['analysis']['_id']}

        analysis = upload.process_upload(self.request, upload.Strategy.analysis, origin=self.origin)
        self.storage.fill_values(analysis, cont_name, cid, self.origin)
        result = self.storage.create_el(analysis)

        if result.acknowledged:
            return {'_id': result.inserted_id}
        else: # cover 100
            self.abort(500, 'Analysis not added for container {} {}'.format(cont_name, cid))

    @validators.verify_payload_exists
    def put(self, cont_name, **kwargs):
        cid = kwargs.pop('cid')
        _id = kwargs.pop('_id')

        parent = self.storage.get_parent(cont_name, cid)
        permchecker = self.get_permchecker(parent)
        permchecker(noop)('PUT')


        payload = self.request.json_body
        self.update_validator(payload, 'PUT')

        payload['modified'] = datetime.datetime.utcnow()

        result = self.storage.update_el(_id, payload)

        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else: # cover 100
            self.abort(404, 'Element not updated in container {} {}'.format(self.storage.cont_name, _id))

    def get(self, cont_name, cid, _id):
        parent = self.storage.get_parent(cont_name, cid)
        permchecker = self.get_permchecker(parent)
        permchecker(noop)('GET')
        return self.storage.get_container(_id)


    @log_access(AccessType.delete_analysis)
    def delete(self, cont_name, cid, _id):
        parent = self.storage.get_parent(cont_name, cid)
        permchecker = self.get_permchecker(parent)
        permchecker(noop)('DELETE')
        self.log_user_access(AccessType.delete_file, cont_name=cont_name, cont_id=cid)

        try:
            result = self.storage.delete_el(_id)
        except APIStorageException as e: # cover 100
            self.abort(400, e.message)
        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else: # cover 100
            self.abort(404, 'Analysis {} not removed from container {} {}'.format(_id, cont_name, cid))


    def download(self, cont_name, cid, _id, filename=None):
        """
        .. http:get:: /api/(cont_name)/(cid)/analyses/(analysis_id)/files/(file_name)

            Download a file from an analysis or download a tar of all files

            When no filename is provided, a tar of all input and output files is created.
            The first request to this endpoint without a ticket ID generates a download ticket.
            A request to this endpoint with a ticket ID downloads the file(s).
            If the analysis object is tied to a job, the input file(s) are inlfated from
            the job's ``input`` array.

            :param cont_name: one of ``projects``, ``sessions``, ``collections``
            :type cont_name: string

            :param cid: Container ID
            :type cid: string

            :param analysis_id: Analysis ID
            :type analysis_id: string

            :param filename: (Optional) Filename of specific file to download
            :type cid: string

            :query string ticket: Download ticket ID

            :statuscode 200: no error
            :statuscode 404: No files on analysis ``analysis_id``
            :statuscode 404: Could not find file ``filename`` on analysis ``analysis_id``

            **Example request without ticket ID**:

            .. sourcecode:: http

                GET /api/sessions/57081d06b386a6dc79ca383c/analyses/5751cd3781460100a66405c8/files HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {
                  "ticket": "57f2af23-a94c-426d-8521-11b2e8782020",
                  "filename": "analysis_5751cd3781460100a66405c8.tar",
                  "file_cnt": 3,
                  "size": 4525137
                }

            **Example request with ticket ID**:

            .. sourcecode:: http

                GET /api/sessions/57081d06b386a6dc79ca383c/analyses/5751cd3781460100a66405c8/files?ticket=57f2af23-a94c-426d-8521-11b2e8782020 HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/octet-stream
                Content-Disposition: attachment; filename=analysis_5751cd3781460100a66405c8.tar;

            **Example Request with filename**:

            .. sourcecode:: http

                GET /api/sessions/57081d06b386a6dc79ca383c/analyses/5751cd3781460100a66405c8/files/exampledicom.zip?ticket= HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {
                  "ticket": "57f2af23-a94c-426d-8521-11b2e8782020",
                  "filename": "exampledicom.zip",
                  "file_cnt": 1,
                  "size": 4525137
                }


        """
        parent = self.storage.get_parent(cont_name, cid)
        permchecker = self.get_permchecker(parent)
        ticket_id = self.get_param('ticket')
        ticket = None
        if ticket_id is None:
            permchecker(noop)('GET')
        elif ticket_id != '':
            ticket = self._check_ticket(ticket_id, cid, filename)
            if not self.origin.get('id'): # cover 100
                self.origin = ticket.get('origin')

        analysis = self.storage.get_container(_id)
        fileinfo = analysis.get('files', [])
        if filename:
            fileinfo = [fi for fi in fileinfo if fi['name'] == filename]

        if not fileinfo:
            error_msg = 'No files on analysis {}'.format(_id)
            if filename:
                error_msg = 'Could not find file {} on analysis {}'.format(filename, _id)
            self.abort(404, error_msg)
        if ticket_id == '':
            if filename:
                total_size = fileinfo[0]['size']
                file_cnt = 1
                ticket = util.download_ticket(self.request.client_addr, 'file', cid, filename, total_size, origin=self.origin)
            else:
                targets, total_size, file_cnt = self._prepare_batch(fileinfo)
                label = util.sanitize_string_to_filename(self.storage.get_container(_id).get('label', 'No Label'))
                filename = 'analysis_' + label + '.tar'
                ticket = util.download_ticket(self.request.client_addr, 'batch', targets, filename, total_size, origin=self.origin)
            return {
                'ticket': config.db.downloads.insert_one(ticket).inserted_id,
                'size': total_size,
                'file_cnt': file_cnt,
                'filename': filename
            }
        else:
            if not filename:
                if ticket:
                    self._send_batch(ticket)
                else: # cover 100
                    self.abort(400, 'batch downloads require a ticket')
            elif not fileinfo: # cover 100
                self.abort(404, "{} doesn't exist".format(filename))
            else:
                fileinfo = fileinfo[0]
                filepath = os.path.join(
                    config.get_item('persistent', 'data_path'),
                    util.path_from_hash(fileinfo['hash'])
                )
                filename = fileinfo['name']

                # Request for info about zipfile
                if self.is_true('info'):
                    try:
                        info = FileListHandler.build_zip_info(filepath)
                    except zipfile.BadZipfile:
                        self.abort(400, 'not a zip file')
                    return info

                # Request to download zipfile member
                elif self.get_param('member') is not None:
                    zip_member = self.get_param('member')
                    try:
                        with zipfile.ZipFile(filepath) as zf:
                            self.response.headers['Content-Type'] = util.guess_mimetype(zip_member)
                            self.response.write(zf.open(zip_member).read())
                    except zipfile.BadZipfile:
                        self.abort(400, 'not a zip file')
                    except KeyError:
                        self.abort(400, 'zip file contains no such member')
                    # log download if we haven't already for this ticket
                    if ticket:
                        if not ticket.get('logged', False):
                            self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cid)
                            config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
                    else: # cover 100
                        self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cid)

                # Request to download the file itself
                else:
                    self.response.app_iter = open(filepath, 'rb')
                    self.response.headers['Content-Length'] = str(fileinfo['size']) # must be set after setting app_iter
                    if self.is_true('view'): # cover 100
                        self.response.headers['Content-Type'] = str(fileinfo.get('mimetype', 'application/octet-stream'))
                    else:
                        self.response.headers['Content-Type'] = 'application/octet-stream'
                        self.response.headers['Content-Disposition'] = 'attachment; filename=' + str(filename)

            # log download if we haven't already for this ticket
            if ticket:
                ticket = config.db.downloads.find_one({'_id': ticket_id})
                if not ticket.get('logged', False):
                    self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cid)
                    config.db.downloads.update_one({'_id': ticket_id}, {'$set': {'logged': True}})
            else: # cover 100
                self.log_user_access(AccessType.download_file, cont_name=cont_name, cont_id=cid)


    def _check_ticket(self, ticket_id, _id, filename):
        ticket = config.db.downloads.find_one({'_id': ticket_id})
        if not ticket:
            self.abort(404, 'no such ticket')
        if ticket['ip'] != self.request.client_addr: # cover 100
            self.abort(400, 'ticket not for this source IP')
        if not filename:
            return self._check_ticket_for_batch(ticket)
        if ticket.get('filename') != filename or ticket['target'] != _id:
            self.abort(400, 'ticket not for this resource')
        return ticket


    def _check_ticket_for_batch(self, ticket):
        if ticket.get('type') != 'batch': # cover 100
            self.abort(400, 'ticket not for this resource')
        return ticket


    def _prepare_batch(self, fileinfo):
        ## duplicated code from download.py
        ## we need a way to avoid this
        targets = []
        total_size = total_cnt = 0
        data_path = config.get_item('persistent', 'data_path')
        for f in fileinfo:
            filepath = os.path.join(data_path, util.path_from_hash(f['hash']))
            if os.path.exists(filepath): # silently skip missing files
                targets.append((filepath, 'analyses/' + f['name'], f['size']))
                total_size += f['size']
                total_cnt += 1
        return targets, total_size, total_cnt


    def _send_batch(self, ticket):
        self.abort(400, 'This endpoint does not download files, only returns ticket {} for the download'.format(ticket))
