"""
A simple FIFO queue for jobs.
"""

import bson
import copy
import pymongo
import datetime

from .. import config
from .jobs import Job, Logs, JobTicket
from .gears import get_gear, validate_gear_config, fill_gear_default_values
from ..dao.containerutil import create_filereference_from_dictionary, create_containerreference_from_dictionary, create_containerreference_from_filereference
from ..web.errors import InputValidationException


log = config.log

JOB_STATES = [
    'pending',  # Job is queued
    'running',  # Job has been handed to an engine and is being processed
    'failed',   # Job has an expired heartbeat (orphaned) or has suffered an error
    'complete', # Job has successfully completed
    'cancelled' # Job has been cancelled (via a bulk job cancellation)
]

JOB_STATES_ALLOWED_MUTATE = [
    'pending',
    'running',
]

JOB_TRANSITIONS = [
    'pending --> running',
    'pending --> cancelled',
    'running --> cancelled',
    'running --> failed',
    'running --> complete',
]

# How many times a job should be retried
def max_attempts():
    return config.get_item('queue', 'max_retries')

# Should a job be retried when explicitly failed.
# Does not affect orphaned jobs.
def retry_on_explicit_fail():
    return config.get_item('queue', 'retry_on_fail')

def valid_transition(from_state, to_state):
    return (from_state + ' --> ' + to_state) in JOB_TRANSITIONS or from_state == to_state

class Queue(object):

    @staticmethod
    def mutate(job, mutation):
        """
        Validate and save a job mutation
        """

        if job.state not in JOB_STATES_ALLOWED_MUTATE:
            raise InputValidationException('Cannot mutate a job that is ' + job.state + '.')

        # TODO: This should use InputValidationException or similar
        if 'state' in mutation and not valid_transition(job.state, mutation['state']):
            raise Exception('Mutating job from ' + job.state + ' to ' + mutation['state'] + ' not allowed.')

        # Any modification must be a timestamp update
        mutation['modified'] = datetime.datetime.utcnow()

        # Create an object with all the fields that must not have changed concurrently.
        job_query =  {
            '_id': bson.ObjectId(job.id_),
            'state': job.state,
        }

        result = config.db.jobs.update_one(job_query, {'$set': mutation})
        if result.modified_count != 1:
            raise Exception('Job modification not saved')

        # If the job did not succeed, check to see if job should be retried.
        if 'state' in mutation and mutation['state'] == 'failed' and retry_on_explicit_fail():
            job.state = 'failed'
            Queue.retry(job)

    @staticmethod
    def retry(job, force=False):
        """
        Given a failed job, either retry the job or fail it permanently, based on the attempt number.
        Can override the attempt limit by passing force=True.
        """

        if job.attempt >= max_attempts() and not force:
            log.info('Permanently failed job %s (after %d attempts)', job.id_, job.attempt)
            return

        if job.state != 'failed':
            raise Exception('Can only retry a job that is failed')

        # Race condition: jobs should only be marked as failed once a new job has been spawned for it (if any).
        # No transactions in our database, so we can't do that.
        # Instead, make a best-hope attempt.
        check = config.db.jobs.find_one({'previous_job_id': job.id_ })
        if check is not None:
            found = Job.load(check)
            raise Exception('Job ' + job.id_ + ' has already been retried as ' + str(found.id_))

        new_job = copy.deepcopy(job)
        new_job.id_ = None
        new_job.previous_job_id = job.id_

        new_job.state = 'pending'
        new_job.attempt += 1

        now = datetime.datetime.utcnow()
        new_job.created = now
        new_job.modified = now

        new_id = new_job.insert()
        log.info('respawned job %s as %s (attempt %d)', job.id_, new_id, new_job.attempt)

        # If job is part of batch job run, update batch jobs list
        result = config.db.batch.update_one(
            {'jobs': job.id_},
            {'$pull': {'jobs': job.id_}, '$push': {'jobs': new_id}}
        )
        if result.modified_count == 1:
            log.info('updated batch job list, replacing {} with {}'.format(job.id_, new_id))

        return new_id


    @staticmethod
    def enqueue_job(job_map, origin, perm_check_uid=None):
        """
        Using a payload for a proposed job, creates and returns (but does not insert)
        a Job object. This preperation includes:
          - confirms gear exists
          - validates config against gear manifest
          - creating file reference objects for inputs
            - if given a perm_check_uid, method will check if user has proper access to inputs
          - confirming inputs exist
          - creating container reference object for destination
          - preparing file contexts
          - job api key generation, if requested

        """

        # gear and config manifest check
        gear_id = job_map.get('gear_id')
        if not gear_id:
            raise InputValidationException('Job must specify gear')

        gear = get_gear(gear_id)

        if gear is None:
            raise InputValidationException('Could not find gear ' + gear_id)

        if gear.get('gear', {}).get('custom', {}).get('flywheel', {}).get('invalid', False):
            raise InputValidationException('Gear marked as invalid, will not run!')

        config_ = fill_gear_default_values(gear, job_map.get('config', {}))
        validate_gear_config(gear, config_)

        # Translate maps to FileReferences
        inputs = {}
        for x in job_map.get('inputs', {}).keys():
            input_map = job_map['inputs'][x]
            try:
                inputs[x] = create_filereference_from_dictionary(input_map)
            except KeyError:
                raise InputValidationException('Input {} does not have a properly formatted file reference.'.format(x))

        # Add job tags, config, attempt number, and/or previous job ID, if present
        tags            = job_map.get('tags', [])
        attempt_n       = job_map.get('attempt_n', 1)
        previous_job_id = job_map.get('previous_job_id', None)
        now_flag        = job_map.get('now', False) # A flag to increase job priority
        batch           = job_map.get('batch', None) # A batch id if this job is part of a batch run

        # Add destination container, or select one
        destination = None
        if job_map.get('destination', None) is not None:
            destination = create_containerreference_from_dictionary(job_map['destination'])
        else:
            if len(inputs.keys()) < 1:
                raise InputValidationException('Must specify destination if gear has no inputs.')

            key = inputs.keys()[0]
            destination = create_containerreference_from_filereference(inputs[key])

        # Permission check
        if perm_check_uid:
            for x in inputs:
                inputs[x].check_access(perm_check_uid, 'ro')
            destination.check_access(perm_check_uid, 'rw')
            now_flag = False # Only superuser requests are allowed to set "now" flag

        # Config options are stored on the job object under the "config" key
        config_ = {
            'config': config_,
            'inputs': { },
            'destination': {
                'type': destination.type,
                'id': destination.id,
            }
        }

        # Implementation notes: with regard to sending the gear file information, we have two options:
        #
        # 1) Send the file object as it existed when you enqueued the job
        # 2) Send the file object as it existed when the job was started
        #
        # Option #2 is possibly more convenient - it's more up to date - but the only file modifications after a job is enqueued would be from
        #
        # A) a gear finishing, and updating the file object
        # B) a user editing the file object
        #
        # You can count on neither occurring before a job starts, because the queue is not globally FIFO.
        # So option #2 is potentially more convenient, but unintuitive and prone to user confusion.

        for x in inputs:

            # Ensure input is in gear manifest
            if x not in gear['gear']['inputs']:
                raise InputValidationException('Job input {} is not listed in gear manifest'.format(x))

            input_type = gear['gear']['inputs'][x]['base']
            if input_type == 'file':

                obj = inputs[x].get_file()
                cr = create_containerreference_from_filereference(inputs[x])

                # Whitelist file fields passed to gear to those that are scientific-relevant
                whitelisted_keys = ['info', 'tags', 'classification', 'mimetype', 'type', 'modality', 'size']
                obj_projection = { key: obj.get(key) for key in whitelisted_keys }

                ###
                # recreate `measurements` list on object
                # Can be removed when `classification` key has been adopted everywhere

                obj_projection['measurements'] = []
                if obj_projection.get('classification'):
                    for v in obj_projection['classification'].itervalues():
                        obj_projection.extend(v)
                #
                ###

                config_['inputs'][x] = {
                    'base': 'file',
                    'hierarchy': cr.__dict__,
                    'location': {
                        'name': obj['name'],
                        'path': '/flywheel/v0/input/' + x + '/' + obj['name'],
                    },
                    'object': obj_projection,
                }
            else:
                # Note: API key inputs should not be passed as input
                raise Exception('Non-file input base type')

        gear_name = gear['gear']['name']

        if gear_name not in tags:
            tags.append(gear_name)

        job = Job(str(gear['_id']), inputs, destination=destination, tags=tags, config_=config_, now=now_flag, attempt=attempt_n, previous_job_id=previous_job_id, origin=origin, batch=batch)
        job.insert()
        return job

    @staticmethod
    def start_job(tags=None):
        """
        Atomically change a 'pending' job to 'running' and returns it. Updates timestamp.
        Will return None if there are no jobs to offer. Searches for jobs marked "now"
        most recently first, followed by unmarked jobs in FIFO order if none are found.

        Potential jobs must match at least one tag, if provided.
        """

        query = { 'state': 'pending', 'now': True }

        if tags is not None:
            query['tags'] = {'$in': tags }

        # First look for jobs marked "now" sorted by modified most recently
        # Mark as running if found
        result = config.db.jobs.find_one_and_update(
            query,

            { '$set': {
                'state': 'running',
                'modified': datetime.datetime.utcnow()}
            },
            sort=[('modified', -1)],
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

        # If no jobs marked "now" are found, search again ordering by FIFO
        if result is None:
            query['now'] = {'$ne': True}
            result = config.db.jobs.find_one_and_update(
                query,

                { '$set': {
                    'state': 'running',
                    'modified': datetime.datetime.utcnow()}
                },
                sort=[('modified', 1)],
                return_document=pymongo.collection.ReturnDocument.AFTER
            )

        if result is None:
            return None

        job = Job.load(result)

        # Return if there is a job request already, else create one
        if job.request is not None:
            log.info('Job ' + job.id_ + ' already has a request, so not generating')
            return job

        else:
            # Generate, save, and return a job request.
            request = job.generate_request(get_gear(job.gear_id))
            result = config.db.jobs.find_one_and_update(
                {
                    '_id': bson.ObjectId(job.id_)
                },
                { '$set': {
                    'request': request }
                },
                return_document=pymongo.collection.ReturnDocument.AFTER
            )

            if result is None:
                raise Exception('Marked job as running but could not generate and save formula')

            return Job.load(result)

    @staticmethod
    def search(containers, states=None, tags=None):
        """
        Search the queue for jobs that mention at least one of a set of containers and (optionally) match some set of states or tags.
        Currently, all containers must be of the same type.

        @param containers: an array of ContainerRefs
        @param states: an array of strings
        @param tags: an array of strings
        """

        # Limitation: container types must match.
        type1 = containers[0].type
        for container in containers:
            if container.type != type1:
                raise Exception('All containers passed to Queue.search must be of the same type')

        query = { '$or': [
            {'inputs.id': {'$in': [x.id for x in containers]}, 'inputs.type': type1},
            {'destination.id': {'$in': [x.id for x in containers]}, 'destination.type': type1},
        ]}

        if states is not None and len(states) > 0:
            query['state'] = {"$in": states}

        if tags is not None and len(tags) > 0:
            query['tags'] = {"$in": tags}

        # For now, mandate reverse-crono sort
        return config.db.jobs.find(query).sort([
            ('modified', pymongo.DESCENDING)
        ])

    @staticmethod
    def get_statistics(tags=None, last=None, unique=False, all_flag=False):
        """
        Return a variety of interesting information about the job queue.
        """

        if all_flag:
            unique = True
            if last is None:
                last = 3

        results = { }
        match = { } # match all jobs

        if tags is not None and len(tags) > 0:
            match = { 'tags': {'$in': tags } } # match only jobs with given tags

        # Count jobs by state, mapping the mongo result to a useful object
        result = list(config.db.jobs.aggregate([{'$match': match }, {'$group': {'_id': '$state', 'count': {'$sum': 1}}}]))
        by_state = {s: 0 for s in JOB_STATES}
        by_state.update({r['_id']: r['count'] for r in result})
        results['states'] = by_state

        # List unique tags
        if unique:
            results['unique'] = sorted(config.db.jobs.distinct('tags'))

        # List recently modified jobs for each state
        if last is not None:
            results['recent'] = {s: config.db.jobs.find({'$and': [match, {'state': s}]}, {'modified':1}).sort([('modified', pymongo.DESCENDING)]).limit(last) for s in JOB_STATES}

        return results

    @staticmethod
    def get_pending(tags=None):
        """
        Returns the same format as get_statistics, but only the pending number.
        Designed to be as efficient as possible for frequent polling :(
        """

        match = { } # match all jobs
        if tags is not None and len(tags) > 0:
            match = { 'tags': {'$in': tags } } # match only jobs with given tags

        return {
            'states': {
                'pending': config.db.jobs.count({'$and': [match, {'state': 'pending'}]})
            }
        }

    @staticmethod
    def scan_for_orphans():
        """
        Scan the queue for orphaned jobs, mark them as failed, and possibly retry them.
        Should be called periodically.
        """

        orphaned = 0
        query = {
            'state': 'running',
            'modified': {'$lt': datetime.datetime.utcnow() - datetime.timedelta(seconds=100)},
        }

        while True:
            orphan_candidate = config.db.jobs.find_one(query)
            if orphan_candidate is None:
                break

            # If the job is currently attempting to complete, do not orphan.
            ticket = JobTicket.find(orphan_candidate['_id'])
            if ticket is not None and len(ticket) > 0:
                continue

            # CAS this job, since it does not have a ticket
            select = { '_id': orphan_candidate['_id'] }

            doc = config.db.jobs.find_one_and_update(
                dict(query, **select),
                {
                    '$set': {
                        'state': 'failed', },
                },
                return_document=pymongo.collection.ReturnDocument.AFTER
            )

            if doc is None:
                log.info('Job %s was heartbeat during a ticket lookup and thus not orhpaned', orphan_candidate['_id'])
            else:
                orphaned += 1
                j = Job.load(doc)
                Logs.add(j.id_, [{'msg':'The job did not report in for a long time and was canceled.', 'fd':-1}])
                new_id = Queue.retry(j)
                Logs.add(j.id_, [{'msg': 'Retried job as ' + str(new_id) if new_id else 'Job retries exceeded maximum allowed', 'fd':-1}])

        return orphaned
