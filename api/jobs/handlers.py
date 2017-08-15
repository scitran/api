"""
API request handlers for the jobs module
"""
import bson
import json
import os
import StringIO
from jsonschema import ValidationError

from .. import upload
from .. import util
from ..auth import require_login, has_access
from ..dao import APIPermissionException
from ..dao.containerstorage import AcquisitionStorage
from ..dao.containerutil import create_filereference_from_dictionary, create_containerreference_from_dictionary, create_containerreference_from_filereference, ContainerReference
from ..web import base
from ..validators import InputValidationException
from .. import config
from . import batch
from ..validators import validate_data

from .gears import validate_gear_config, get_gears, get_gear, get_invocation_schema, remove_gear, upsert_gear, suggest_container
from .jobs import Job, Logs
from .batch import check_state, update
from .queue import Queue


class GearsHandler(base.RequestHandler):

    """Provide /gears API routes."""

    def get(self):
        """List all gears."""

        if self.public_request:
            self.abort(403, 'Request requires login')

        gears   = get_gears()
        filters = self.request.GET.getall('filter')

        if 'single_input' in filters: # cover 100
            gears = list(filter(lambda x: len(x["gear"]["inputs"].keys()) <= 1, gears))

        return gears

class GearHandler(base.RequestHandler):
    """Provide /gears/x API routes."""

    def get(self, _id):
        """Detail a gear."""

        if self.public_request:
            self.abort(403, 'Request requires login')

        return get_gear(_id)

    def get_invocation(self, _id):

        if self.public_request:
            self.abort(403, 'Request requires login')

        gear = get_gear(_id)
        return get_invocation_schema(gear)

    def suggest(self, _id, cont_name, cid):

        if self.public_request:
            self.abort(403, 'Request requires login')

        cr = ContainerReference(cont_name, cid)
        if not self.superuser_request:
            cr.check_access(self.uid, 'ro')

        gear = get_gear(_id)
        return suggest_container(gear, cont_name+'s', cid)

    # Temporary Function
    def upload(self): # pragma: no cover
        """Upload new gear tarball file"""
        if not self.user_is_admin:
            self.abort(403, 'Request requires admin')

        r = upload.process_upload(self.request, upload.Strategy.gear, container_type='gear', origin=self.origin, metadata=self.request.headers.get('metadata'))
        gear_id = upsert_gear(r[1])
        config.db.gears.update_one({'_id': gear_id}, {'$set': {
            'exchange.rootfs-url': '/api/gears/temp/' + str(gear_id)}
        })

        return {'_id': str(gear_id)}

    # Temporary Function
    def download(self, **kwargs): # pragma: no cover
        """Download gear tarball file"""
        dl_id = kwargs.pop('cid')
        gear = get_gear(dl_id)
        hash_ = gear['exchange']['rootfs-hash']
        filepath = os.path.join(config.get_item('persistent', 'data_path'), util.path_from_hash('v0-' + hash_.replace(':', '-')))
        self.response.app_iter = open(filepath, 'rb')
        # self.response.headers['Content-Length'] = str(gear['size']) # must be set after setting app_iter
        self.response.headers['Content-Type'] = 'application/octet-stream'
        self.response.headers['Content-Disposition'] = 'attachment; filename="gear.tar"'


    def post(self, _id):
        """Upsert an entire gear document."""
        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')

        doc = self.request.json

        if _id != doc.get('gear', {}).get('name', ''):
            self.abort(400, 'Name key must be present and match URL')

        try:
            result = upsert_gear(self.request.json)
            return { '_id': str(result) }

        except ValidationError as err:
            key = "none"
            if len(err.relative_path) > 0: # cover 100
                key = err.relative_path[0]

            message = err.message.replace("u'", "'")

            raise InputValidationException('Gear manifest does not match schema on key ' + key + ': ' + message)

    def delete(self, _id):
        """Delete a gear. Generally not recommended."""
        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')

        return remove_gear(_id)

class RulesHandler(base.RequestHandler):

    def get(self, cid):
        """List rules"""

        project = config.db.projects.find_one({'_id': bson.ObjectId(cid)})

        if project and (self.superuser_request or has_access(self.uid, project, 'ro')):
            return config.db.project_rules.find({'project_id' : cid})
        else:
            self.abort(404, 'Project not found')

    def post(self, cid):
        """Add a rule"""

        project = config.db.projects.find_one({'_id': bson.ObjectId(cid)})

        if project:
            if self.superuser_request or has_access(self.uid, project, 'admin'):
                doc = self.request.json

                validate_data(doc, 'rule-add.json', 'input', 'POST', optional=True)

                doc['project_id'] = cid

                result = config.db.project_rules.insert_one(doc)
                return { '_id': result.inserted_id }

            elif has_access(self.uid, project, 'ro'):
                self.abort(403, 'Adding rules to a project can only be done by a project admin.')

        self.abort(404, 'Project not found')

class RuleHandler(base.RequestHandler):

    def get(self, cid, rid):
        """Get rule"""

        project = config.db.projects.find_one({'_id': bson.ObjectId(cid)})

        if project and (self.superuser_request or has_access(self.uid, project, 'ro')):
            result = config.db.project_rules.find_one({'project_id' : cid, '_id': bson.ObjectId(rid)})
            if result:
                return result
            else:
                self.abort(404, 'Rule not found')
        else:
            self.abort(404, 'Project not found')

    def put(self, cid, rid):
        """Change a rule"""

        project = config.db.projects.find_one({'_id': bson.ObjectId(cid)})

        if project:
            if self.superuser_request or has_access(self.uid, project, 'admin'):
                result = config.db.project_rules.find_one({'project_id' : cid, '_id': bson.ObjectId(rid)})
                if result is None:
                    self.abort(404, 'Rule not found')

                doc = self.request.json
                validate_data(doc, 'rule-update.json', 'input', 'POST', optional=True)

                doc['_id']        = result['_id']
                doc['project_id'] = cid

                config.db.project_rules.update_one({'_id': bson.ObjectId(rid)}, {'$set': doc })
                return

            elif has_access(self.uid, project, 'ro'):
                self.abort(403, 'Changing project rules can only be done by a project admin.')

        self.abort(404, 'Project not found')

    def delete(self, cid, rid):
        """Remove a rule"""

        project = config.db.projects.find_one({'_id': bson.ObjectId(cid)})

        if project:
            if self.superuser_request or has_access(self.uid, project, 'admin'):

                result = config.db.project_rules.delete_one({'project_id' : cid, '_id': bson.ObjectId(rid)})
                if result.deleted_count != 1:
                    self.abort(404, 'Rule not found')
                return

            elif has_access(self.uid, project, 'ro'):
                self.abort(403, 'Changing project rules can only be done by a project admin.')

        self.abort(404, 'Project not found')

class JobsHandler(base.RequestHandler):
    """Provide /jobs API routes."""
    def get(self): # pragma: no cover (no route)
        """List all jobs."""
        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')
        return list(config.db.jobs.find())

    def add(self):
        """Add a job to the queue."""
        submit = self.request.json

        gear_id = str(submit['gear_id'])

        # Translate maps to FileReferences
        inputs = {}
        for x in submit['inputs'].keys():
            input_map = submit['inputs'][x]
            inputs[x] = create_filereference_from_dictionary(input_map)

        # Add job tags, config, attempt number, and/or previous job ID, if present
        tags            = submit.get('tags', [])
        config_         = submit.get('config', {})
        attempt_n       = submit.get('attempt_n', 1)
        previous_job_id = submit.get('previous_job_id', None)
        now_flag        = submit.get('now', False) # A flag to increase job priority

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
            now_flag = False # Only superuser requests are allowed to set "now" flag

        # Config manifest check
        gear = get_gear(gear_id)

        if gear is None:
            self.abort(400, 'Could not find gear ' + gear_id)

        if gear.get('gear', {}).get('custom', {}).get('flywheel', {}).get('invalid', False):
            self.abort(400, 'Gear marked as invalid, will not run!')
        validate_gear_config(gear, config_)

        gear_name = gear['gear']['name']

        if gear_name not in tags:
            tags.append(gear_name)

        job = Job(gear_id, inputs, destination=destination, tags=tags, config_=config_, now=now_flag, attempt=attempt_n, previous_job_id=previous_job_id, origin=self.origin)
        result = job.insert()

        return { '_id': result }

    def stats(self):
        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')

        return Queue.get_statistics()

    def next(self):

        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')


        tags = self.request.GET.getall('tags')
        if len(tags) <= 0:
            tags = None

        job = Queue.start_job(tags=tags)

        if job is None:
            self.abort(400, 'No jobs to process')
        else:
            return job

    def reap_stale(self):
        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')

        count = Queue.scan_for_orphans()
        return { 'orphaned': count }


class JobHandler(base.RequestHandler):
    """Provides /Jobs/<jid> routes."""

    def get(self, _id):

        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')


        return Job.get(_id)

    def get_config(self, _id):
        """Get a job's config"""
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        c = Job.get(_id).config
        if c is None: # cover 100
            c = {}

        self.response.headers['Content-Type'] = 'application/octet-stream'
        self.response.headers['Content-Disposition'] = 'attachment; filename="config.json"'

        # Serve config as formatted json file
        encoded = json.dumps({"config": c}, sort_keys=True, indent=4, separators=(',', ': ')) + '\n'
        self.response.app_iter = StringIO.StringIO(encoded)

    @require_login
    def put(self, _id):
        """
        Update a job. Updates timestamp.
        Enforces a valid state machine transition, if any.
        Rejects any change to a job that is not currently in 'pending' or 'running' state.
        """
        j = Job.get(_id)
        mutation = self.request.json

        # If user is not superuser, can only cancel jobs they spawned
        if not self.superuser_request and not self.user_is_admin:
            if j.origin.get('id') != self.uid:
                raise APIPermissionException('User does not have permission to access job {}'.format(_id))
            if mutation != {'state': 'cancelled'}:
                raise APIPermissionException('User can only cancel jobs.')

        Queue.mutate(j, mutation)

        # If the job failed or succeeded, check state of the batch
        if 'state' in mutation and mutation['state'] in ['complete', 'failed'] and j.batch:
            batch_id = j.batch
            new_state = check_state(batch_id)
            if new_state:
                update(batch_id, {'state': new_state})


    def _log_read_check(self, _id):
        try:
            job = Job.get(_id)
        except Exception: # pylint: disable=broad-except
            self.abort(404, 'Job not found')

        # Permission check
        if not self.superuser_request:
            for x in job.inputs:
                job.inputs[x].check_access(self.uid, 'ro')
            # Unlike jobs-add, explicitly not checking write access to destination.


    def get_logs(self, _id):
        """Get a job's logs"""

        self._log_read_check(_id)
        return Logs.get(_id)

    def get_logs_text(self, _id):
        """Get a job's logs in raw text"""

        self._log_read_check(_id)

        self.response.headers['Content-Type'] = 'application/octet-stream'
        self.response.headers['Content-Disposition'] = 'attachment; filename="job-' + _id + '-logs.txt"'

        for output in Logs.get_text_generator(_id):
            self.response.write(output)

        return

    def get_logs_html(self, _id):
        """Get a job's logs in html"""

        self._log_read_check(_id)

        for output in Logs.get_html_generator(_id):
            self.response.write(output)

        return

    def add_logs(self, _id):
        """Add to a job's logs"""
        if not self.superuser_request and not self.user_is_admin:
            self.abort(403, 'Request requires admin')


        doc = self.request.json

        try:
            Job.get(_id)
        except Exception: # pylint: disable=broad-except
            self.abort(404, 'Job not found')

        return Logs.add(_id, doc)

    def retry(self, _id):
        """ Retry a job.

        The job must have a state of 'failed', and must not have already been retried.
        Returns the id of the new, generated job.
        """
        j = Job.get(_id)

        # Permission check
        if not self.superuser_request:
            for x in j.inputs:
                j.inputs[x].check_access(self.uid, 'ro')
            j.destination.check_access(self.uid, 'rw')

        new_id = Queue.retry(j, force=True)
        return { "_id": new_id }

class BatchHandler(base.RequestHandler):

    @require_login
    def get_all(self):
        """
        Get a list of batch jobs user has created.
        Make a superuser request to see all batch jobs.
        """

        if self.superuser_request:
            # Don't enforce permissions for superuser requests or drone requests
            query = {}
        else:
            query = {'origin.id': self.uid}
        return batch.get_all(query, {'proposal':0})

    @require_login
    def get(self, _id):
        """
        Get a batch job by id.
        Use param jobs=true to replace job id list with job objects.
        """

        get_jobs = self.is_true('jobs')
        batch_job = batch.get(_id, projection={'proposal':0}, get_jobs=get_jobs)
        self._check_permission(batch_job)
        return batch_job

    @require_login
    def post(self):
        """
        Create a batch job proposal, insert as 'pending' if there are matched containers
        """

        payload = self.request.json
        gear_id = payload.get('gear_id')
        targets = payload.get('targets')
        config_ = payload.get('config', {})
        analysis_data = payload.get('analysis', {})
        tags = payload.get('tags', [])

        # Request might specify a collection context
        collection_id = payload.get('target_context', {}).get('id', None)
        if collection_id:
            collection_id = bson.ObjectId(collection_id)

        # Validate the config against the gear manifest
        if not gear_id or not targets:
            self.abort(400, 'A gear name and list of target containers is required.')
        gear = get_gear(gear_id)
        if gear.get('gear', {}).get('custom', {}).get('flywheel', {}).get('invalid', False):
            self.abort(400, 'Gear marked as invalid, will not run!')
        validate_gear_config(gear, config_)

        container_ids = []
        container_type = None

        # Get list of container ids from target list
        for t in targets:
            if not container_type:
                container_type = t.get('type')
            else:
                # Ensure all targets are of same type, may change in future
                if container_type != t.get('type'):
                    self.abort(400, 'targets must all be of same type.')
            container_ids.append(t.get('id'))

        # Get acquisitions associated with targets
        objectIds = [bson.ObjectId(x) for x in container_ids]
        containers = AcquisitionStorage().get_all_for_targets(container_type, objectIds,
            collection_id=collection_id, include_archived=False)

        if not containers:
            self.abort(404, 'Could not find acquisitions from targets.')

        improper_permissions = []
        acquisitions = []

        # Make sure user has read-write access, add those to acquisition list
        for c in containers:
            if self.superuser_request or has_access(self.uid, c, 'rw'):
                c.pop('permissions')
                acquisitions.append(c)
            else:
                improper_permissions.append(c['_id'])

        if not acquisitions:
            self.abort(403, 'User does not have write access to targets.')

        results = batch.find_matching_conts(gear, acquisitions, 'acquisition')

        matched = results['matched']
        batch_proposal = {}

        # If there are matches, create a batch job object and insert it
        if matched:

            batch_proposal = {
                '_id': bson.ObjectId(),
                'gear_id': gear_id,
                'config': config_,
                'state': 'pending',
                'origin': self.origin,
                'proposal': {
                    'inputs': [c.pop('inputs') for c in matched],
                    'analysis': analysis_data,
                    'tags': tags
                }
            }

            batch.insert(batch_proposal)
            batch_proposal.pop('proposal')

        # Either way, return information about the status of the containers
        batch_proposal['not_matched'] = results['not_matched']
        batch_proposal['ambiguous'] = results['ambiguous']
        batch_proposal['matched'] = matched
        batch_proposal['improper_permissions'] = improper_permissions

        return batch_proposal

    @require_login
    def run(self, _id):
        """
        Creates jobs from proposed inputs, returns jobs enqueued.
        Moves 'pending' batch job to 'running'.
        """

        batch_job = batch.get(_id)
        self._check_permission(batch_job)
        if batch_job.get('state') != 'pending':
            self.abort(400, 'Can only run pending batch jobs.')
        return batch.run(batch_job)

    @require_login
    def cancel(self, _id):
        """
        Cancels jobs that are still pending, returns number of jobs cancelled.
        Moves a 'running' batch job to 'cancelled'.
        """

        batch_job = batch.get(_id)
        self._check_permission(batch_job)
        if batch_job.get('state') != 'running':
            self.abort(400, 'Can only cancel started batch jobs.')
        return {'number_cancelled': batch.cancel(batch_job)}

    def _check_permission(self, batch_job):
        if not self.superuser_request:
            if batch_job['origin'].get('id') != self.uid:
                raise APIPermissionException('User does not have permission to access batch {}'.format(batch_job.get('_id')))
