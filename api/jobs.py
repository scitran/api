"""
API request handlers for process-job-handling.
"""

# We shadow the standard library; this is a workaround.
from __future__ import absolute_import

import bson
import pymongo
import datetime
from collections import namedtuple

from . import base
from . import config
from . import util

log = config.log

# How many times a job should be retried
MAX_ATTEMPTS = 3

JOB_STATES = [
    'pending',  # Job is queued
    'running',  # Job has been handed to an engine and is being processed
    'failed',   # Job has an expired heartbeat (orphaned) or has suffered an error
    'complete', # Job has successfully completed
]

JOB_STATES_ALLOWED_MUTATE = [
    'pending',
    'running',
]

JOB_TRANSITIONS = [
    'pending --> running',
    'running --> failed',
    'running --> complete',
]

def valid_transition(from_state, to_state):
    return (from_state + ' --> ' + to_state) in JOB_TRANSITIONS or from_state == to_state

Category = util.Enum('Category', {
    'classifier': 'classifier', # discover metadata
    'converter':  'converter',  # translate between formats
    'qa':         'qa',         # quality assurance
    'analytical': 'analytical', # general purpose
})

Gear = namedtuple('gear', ['name', 'category', 'input'])

Gears = [
    Gear('dicom_mr_classifier', Category.classifier, {'type': 'file', 'location': '/', 'uri': '/opt/flywheel-temp/dicom_mr_classifier-0.0.1.c.tar'}),
    Gear('dcm_convert',         Category.converter,  {'type': 'file', 'location': '/', 'uri': '/opt/flywheel-temp/dcm_convert-0.3.0.c.tar'      }),
    Gear('qa-report-fmri',      Category.qa,         {'type': 'file', 'location': '/', 'uri': '/opt/flywheel-temp/qa-report-fmri-0.1.0.c.tar'     })
]

def get_gear_by_name(name):
    for gear in Gears:
        if gear.name == name:
            return gear
    raise Exception("Unknown gear " + name)

# A FileInput tuple holds all the details of a scitran file that needed to use that as an input a formula.
FileInput = namedtuple('input', ['container_type', 'container_id', 'filename', 'filehash'])

# Convert a dictionary to a FileInput
def convert_to_fileinput(d):
    if d['container_type'].endswith('s'):
        raise Exception('Container type cannot be plural :|')

    return FileInput(
        container_type= d['container_type'],
        container_id  = d['container_id'],
        filename      = d['filename'],
        filehash      = d['filehash']
    )

def create_fileinput_from_reference(container, container_type, file_):
    """
    Spawn a job to process a file.

    Parameters
    ----------
    container: scitran.Container
        A container object that the file is held by
    container_type: string
        The type of container (eg, 'session')
    file: scitran.File
        File object that is used to spawn 0 or more jobs.
    """

    # File information
    filename = file_['name']
    filehash = file_['hash']
    # File container information
    container_id = str(container['_id'])

    log.info('File ' + filename + 'is in a ' + container_type + ' with id ' + container_id + ' and hash ' + filehash)

    # Spawn rules currently do not look at container hierarchy, and only care about a single file.
    # Further, one algorithm is unconditionally triggered for each dirty file.

    return FileInput(container_type=container_type, container_id=container_id, filename=filename, filehash=filehash)


def queue_job(db, algorithm_id, input, tags=[], attempt_n=1, previous_job_id=None):
    """
    Enqueues a job for execution.

    Parameters
    ----------
    db: pymongo.database.Database
        Reference to the database instance
    algorithm_id: string
        Human-friendly unique name of the algorithm
    input: FileInput
        The input to be used by this job
    tags: string array (optional)
        Tags that this job should be marked with.
    attempt_n: integer (optional)
        If an equivalent job has tried & failed before, pass which attempt number we're at. Defaults to 1 (no previous attempts).
    """

    gear = get_gear_by_name(algorithm_id)

    if input.container_type.endswith('s'):
        raise Exception('Container type cannot be plural :|')

    # TODO validate container exists

    now = datetime.datetime.utcnow()

    # Job tags allow consumers to filter on job attributes.
    # The algorithm name and category are always tagged; callee can provide others.
    hardcoded_tags = [ gear.name, str(gear.category) ]
    # Union of two arrays
    tags = list(set(hardcoded_tags) | set(tags))

    job = {
        'state': 'pending',

        'created':  now,
        'modified': now,

        'algorithm_id': gear.name,
        'input': input._asdict(),

        'attempt': attempt_n,
        'tags': tags
    }

    if previous_job_id is not None:
        job['previous_job_id'] = previous_job_id

    result = db.jobs.insert_one(job)
    _id = result.inserted_id

    log.info('Enqueuing %s as job %s to process %s %s' % (gear.name, str(_id), input.container_type, input.container_id))
    return _id

def retry_job(db, j, force=False):
    """
    Given a failed job, either retry the job or fail it permanently, based on the attempt number.
    Can override the attempt limit by passing force=True.
    """

    if j['attempt'] < MAX_ATTEMPTS or force:
        job_id = queue_job(db, j['algorithm_id'], convert_to_fileinput(j['input']), attempt_n=j['attempt']+1, previous_job_id=j['_id'])
        log.info('respawned job %s as %s (attempt %d)' % (j['_id'], job_id, j['attempt']+1))
    else:
        log.info('permanently failed job %s (after %d attempts)' % (j['_id'], j['attempt']))


def generate_formula(algorithm_id, i):
    """
    Given an intent, generates a formula to execute a job.

    Parameters
    ----------
    algorithm_id: string
        Human-friendly unique name of the algorithm
    i: FileInput
        The input to be used by this job
    """

    gear = get_gear_by_name(algorithm_id)

    f = {
        'inputs': [
            gear.input,
            {
                'type': 'scitran',
                'uri': '/' + i['container_type'] + 's/' + i['container_id'] + '/files/' + i['filename'],
                'location': '/flywheel/v0/input',
            }
        ],
        'target': {
            'command': ['bash', '-c', 'rm -rf output; mkdir -p output; sed -i \'s/_dicom//\' run; ./run; echo "Exit was $?"'],
            'env': {
                'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
            },
            'dir': "/flywheel/v0",
        },
        'outputs': [
            {
                'type': 'scitran',
                'uri': '/engine?level=' + i['container_type'] + '&id=' + i['container_id'],
                'location': '/flywheel/v0/output',
            },
        ],
    }

    return f


class Jobs(base.RequestHandler):

    """Provide /jobs API routes."""

    def get(self):
        """
        List all jobs. Not used by engine.
        """
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        results = list(config.db.jobs.find())

        return results

    def count(self):
        """Return the total number of jobs. Not used by engine."""
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        return config.db.jobs.count()

    def stats(self):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        # Count jobs by state
        result = config.db.jobs.aggregate([{"$group": {"_id": "$state", "count": {"$sum": 1}}}])
        # Map mongo result to a useful object
        by_state = {s: 0 for s in JOB_STATES}
        by_state.update({r['_id']: r['count'] for r in result})

        # Count jobs by tag grouping
        result = list(config.db.jobs.aggregate([{"$group": {"_id": "$tags", "count": {"$sum": 1}}}]))
        by_tag = []
        for r in result:
            by_tag.append({'tags': r['_id'], 'count': r['count']})

        # Count jobs that will not be retried
        permafailed = config.db.jobs.count({"attempt": {"$gte": MAX_ATTEMPTS}, "state":"failed"})

        return {
            'by-state': by_state,
            'by-tag': by_tag,
            'permafailed': permafailed
        }

    def next(self):
        """
        Atomically change a 'pending' job to 'running' and returns it. Updates timestamp.
        Will return empty if there are no jobs to offer.
        Engine will poll this endpoint whenever there are free processing slots.
        """
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        # First, atomically mark document as running.
        result = config.db.jobs.find_one_and_update(
            {
                'state': 'pending'
            },
            { '$set': {
                'state': 'running',
                'modified': datetime.datetime.utcnow()}
            },
            sort=[('modified', 1)],
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

        if result is None:
            self.abort(400, 'No jobs to process')

        # Second, update document to store formula request.
        result = config.db.jobs.find_one_and_update(
            {
                '_id': result['_id']
            },
            { '$set': {
                'request': generate_formula(result['algorithm_id'], result['input'])}
            },
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

        if result is None:
            self.abort(500, 'Marked job as running but could not generate and save formula')

        return result

    def reap_stale(self):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        while True:
            j = config.db.jobs.find_one_and_update(
                {
                    'state': 'running',
                    'modified': {'$lt': datetime.datetime.utcnow() - datetime.timedelta(seconds=100)},
                },
                {
                    '$set': {
                        'state': 'failed',
                    },
                },
                )
            if j is None:
                break
            else:
                retry_job(config.db, j)


class Job(base.RequestHandler):

    """Provides /Jobs/<jid> routes."""

    def get(self, _id):
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        result = config.db.jobs.find_one({'_id': bson.ObjectId(_id)})
        return result

    def put(self, _id):
        """
        Update a job. Updates timestamp.
        Enforces a valid state machine transition, if any.
        Rejects any change to a job that is not currently in 'pending' or 'running' state.
        """
        if not self.superuser_request:
            self.abort(403, 'Request requires superuser')

        mutation = self.request.json
        job = config.db.jobs.find_one({'_id': bson.ObjectId(_id)})

        if job is None:
            self.abort(404, 'Job not found')

        if job['state'] not in JOB_STATES_ALLOWED_MUTATE:
            self.abort(404, 'Cannot mutate a job that is ' + job['state'] + '.')

        if 'state' in mutation and not valid_transition(job['state'], mutation['state']):
            self.abort(404, 'Mutating job from ' + job['state'] + ' to ' + mutation['state'] + ' not allowed.')

        # Any modification must be a timestamp update
        mutation['modified'] = datetime.datetime.utcnow()

        # Create an object with all the fields that must not have changed concurrently.
        job_query =  {
            '_id': job['_id'],
            'state': job['state'],
        }

        result = config.db.jobs.update_one(job_query, {'$set': mutation})
        if result.modified_count != 1:
            self.abort(500, 'Job modification not saved')

        # If the job did not succeed, check to see if job should be retried.
        if 'state' in mutation and mutation['state'] == 'failed':
            job = config.db.jobs.find_one({'_id': bson.ObjectId(_id)})
            retry_job(config.db, job)
