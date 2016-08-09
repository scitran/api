"""
API request handlers for the jobs module
"""

import json
import StringIO

from ..dao.containerutil import create_filereference_from_dictionary, create_containerreference_from_dictionary, create_containerreference_from_filereference
from .. import base
from .. import config

from .gears import get_gears, get_gear_by_name, remove_gear, upsert_gear
from .jobs import Job
from .queue import Queue

log = config.log


class GearsHandler(base.RequestHandler):

    """Provide /gears API routes."""

    def get(self):
        """
        .. http:get:: /api/gears

            List all gears.

            :query fields: filter fields returned. Defaults to ['name']. Pass 'all' for everything.
            :type fields: string

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                GET /api/gears HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                [
                    {
                        "name": "dicom_mr_classifier"
                    },
                    {
                        "name": "dcm_convert"
                    },
                    {
                        "name": "qa-report-fmri"
                    }
                ]
        """

        if self.public_request:
            self.abort(403, 'Request requires login')

        fields = self.request.GET.getall('fields')
        if 'all' in fields:
            fields = None

        return get_gears(fields)

class GearHandler(base.RequestHandler):

    """Provide /gears/x API routes."""

    def get(self, _id):
        """
        .. http:get:: /api/gears/(gid)

            Detail a gear.

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                GET /api/gears/dcm_convert HTTP/1.1

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json; charset=utf-8
                {
                    "name": "dcm_convert"
                    "manifest": {
                        "config": {},
                        "inputs": {
                            "dicom": {
                                "base": "file",
                                "type": {
                                    "enum": [
                                        "dicom"
                                    ]
                                }
                            }
                        },
                    },
                }

        """

        if self.public_request:
            self.abort(403, 'Request requires login')

        return get_gear_by_name(_id)

    def post(self, _id):
        """
        .. http:post:: /api/gears/(gid)

            Upsert an entire gear document.

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                POST /api/gears/dicom_mr_classifier HTTP/1.1
                {
                    "name": "dicom_mr_classifier",
                    "category": "classifier",
                    "input": {
                        // ...
                    },
                    "manifest": {
                        // ..
                    }
                }

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json; charset=utf-8
                { "name": "dicom_mr_classifier" }
        """

        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        doc = self.request.json

        if _id != doc.get('name', ''):
            self.abort(400, 'Name key must be present and match URL')

        upsert_gear(self.request.json)
        return { 'name': _id }

    def delete(self, _id):
        """
        .. http:delete:: /api/gears/(gid)

            Delete a gear. Generally not recommended.

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                DELETE /api/gears/dicom_mr_classifier HTTP/1.1

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
        """

        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        return remove_gear(_id)


class RulesHandler(base.RequestHandler):

    """Provide /rules API routes."""

    def get(self):
        """
        .. http:get:: /api/rules

            List gear rules.

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                GET /api/rules HTTP/1.1

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Type: application/json; charset=utf-8
                [
                    {
                        "alg" : "dicom_mr_classifier",
                        "all" : [
                            [
                                "file.type",
                                "dicom"
                            ]
                        ]
                    },
                ]
        """

        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        return config.db.singletons.find_one({"_id" : "rules"})['rule_list']

    def post(self):
        """
        .. http:post:: /api/rules

            Upsert all rules

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                POST /api/rules HTTP/1.1
                [
                    {
                        "alg" : "dicom_mr_classifier",
                        "all" : [
                            [
                                "file.type",
                                "dicom"
                            ]
                        ]
                    },
                ]

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
        """

        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        doc = self.request.json
        config.db.singletons.replace_one({"_id" : "rules"}, {'rule_list': doc}, upsert=True)


class JobsHandler(base.RequestHandler):

    """Provide /jobs API routes."""

    def get(self):
        """
        List all jobs.
        """
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        return list(config.db.jobs.find())

    def add(self):
        """
        .. http:post:: /api/jobs/add

            Add a job to the queue.

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                POST /api/jobs/add HTTP/1.1

                {
                    "gear": "dcm_convert",

                    "inputs": {
                        "dicom": {
                            "type": "acquisition",
                            "id": "573c9e6a844eac7fc01747cd",
                            "name" : "1_1_dicom.zip"
                        }
                    },

                    "destination": {
                        "type": "acquisition",
                        "id": "573c9e6a844eac7fc01747cd"
                    },

                    "tags": [
                        "ad-hoc"
                    ]
                }

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {
                    "_id": "573cb66b135d87002660597c"
                }
        """

        submit = self.request.json

        gear_name = submit['gear']

        # Translate maps to FileReferences
        inputs = {}
        for x in submit['inputs'].keys():
            input_map = submit['inputs'][x]
            inputs[x] = create_filereference_from_dictionary(input_map)

        # Add job tags, config, attempt number, and/or previous job ID, if present
        tags            = submit.get('tags', None)
        config_         = submit.get('config', None)
        attempt_n       = submit.get('attempt_n', 1)
        previous_job_id = submit.get('previous_job_id', None)

        # Add destination container, or select one
        destination = None
        if submit.get('destination', None) is not None:
            destination = create_containerreference_from_dictionary(submit['destination'])
        else:
            key = inputs.keys()[0]
            destination = create_containerreference_from_filereference(inputs[key])

        # Permission check
        if not self.superuser_request:
            for x in inputs:
                inputs[x].check_access(self.uid, 'ro')
            destination.check_access(self.uid, 'rw')

        job = Job(gear_name, inputs, destination=destination, tags=tags, config_=config_, attempt=attempt_n, previous_job_id=previous_job_id)
        result = job.insert()

        return { "_id": result }

    def stats(self):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        return Queue.get_statistics()

    def next(self):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        tags = self.request.GET.getall('tags')
        if len(tags) <= 0:
            tags = None

        job = Queue.start_job(tags=tags)

        if job is None:
            self.abort(400, 'No jobs to process')
        else:
            return job

    def reap_stale(self):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        count = Queue.scan_for_orphans()
        return { 'orphaned': count }


class JobHandler(base.RequestHandler):

    """Provides /Jobs/<jid> routes."""

    def get(self, _id):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        return Job.get(_id)

    def get_config(self, _id):
        """
        .. http:get:: /api/jobs/x/config.json

            Returns the job's config as a downloadable json file

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                GET /api/jobs/3/config.json HTTP/1.1

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Content-Disposition: attachment; filename="config.json"
                Content-Type: application/octet-stream

                {
                    "speed": 5
                }
        """

        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        c = Job.get(_id).config
        if c is None:
            c = {}

        self.response.headers['Content-Type'] = 'application/octet-stream'
        self.response.headers['Content-Disposition'] = 'attachment; filename="config.json"'

        # Serve config as formatted json file
        encoded = json.dumps(c, sort_keys=True, indent=4, separators=(',', ': ')) + '\n'
        self.response.app_iter = StringIO.StringIO(encoded)

    def put(self, _id):
        """
        Update a job. Updates timestamp.
        Enforces a valid state machine transition, if any.
        Rejects any change to a job that is not currently in 'pending' or 'running' state.
        """
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        j = Job.get(_id)
        Queue.mutate(j, self.request.json)

    def retry(self, _id):
        """
        .. http:post:: /api/jobs/(jid)/retry

            Retry a job.

            The job must have a state of 'failed', and must not have already been retried.
            Returns the id of the new, generated job.

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                POST /api/jobs/3/retry HTTP/1.1

            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {
                    "_id": "573cb66b135d87002660597c"
                }
        """

        j = Job.get(_id)

        # Permission check
        if not self.superuser_request:
            for x in j.inputs:
                j.inputs[x].check_access(self.uid, 'ro')
            j.destination.check_access(self.uid, 'rw')

        new_id = Queue.retry(j, force=True)
        return { "_id": new_id }
