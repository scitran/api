import bson.errors
import bson.objectid
import datetime

from .. import config
from .. import util
from . import consistencychecker, containerutil
from . import APIStorageException, APIConflictException
from .containerstorage import SessionStorage, AcquisitionStorage
from .containerutil import create_filereference_from_dictionary, create_containerreference_from_dictionary, create_containerreference_from_filereference
from ..jobs.jobs import Job
from ..jobs.gears import validate_gear_config, get_gear

log = config.log


class ListStorage(object):
    """
    This class provides access to sublists of a mongodb collections elements (called containers).
    It is used by ListHandler istances for get, create, update and delete operations on sublist of the containers.
    Examples: permissions in projects, roles in groups, notes in projects, sessions, acquisitions, etc
    """

    def __init__(self, cont_name, list_name, use_object_id = False):
        self.cont_name = cont_name
        self.list_name = list_name
        self.use_object_id = use_object_id
        self.dbc = config.db[cont_name]

    def get_container(self, _id, query_params=None):
        """
        Load a container from the _id.

        This method is usually used to to check permission properties of the container.
        e.g. list of users that can access the container

        For simplicity we load its full content.
        """
        if self.use_object_id:
            _id = bson.objectid.ObjectId(_id)
        query = {'_id': _id}
        projection = None
        if query_params:
            query[self.list_name] = {
                '$elemMatch': query_params
            }
            projection = {self.list_name + '.$': 1, 'permissions': 1, 'public': 1}
        log.debug('query {}'.format(query))
        return self.dbc.find_one(query, projection)

    def exec_op(self, action, _id=None, query_params=None, payload=None, exclude_params=None):
        """
        Generic method to exec an operation.
        The request is dispatched to the corresponding private methods.
        """
        check = consistencychecker.get_list_storage_checker(action, self.list_name)
        check(payload)
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        if action == 'GET':
            return self._get_el(_id, query_params)
        if action == 'DELETE':
            return self._delete_el(_id, query_params)
        if action == 'PUT':
            return self._update_el(_id, query_params, payload, exclude_params)
        if action == 'POST':
            return self._create_el(_id, payload, exclude_params)
        raise ValueError('action should be one of GET, POST, PUT, DELETE')

    def _create_el(self, _id, payload, exclude_params):
        log.debug('payload {}'.format(payload))
        query = {'_id': _id}
        if exclude_params:
            query[self.list_name] = {'$not': {'$elemMatch': exclude_params} }
        update = {'$push': {self.list_name: payload} }
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        result = self.dbc.update_one(query, update)
        if result.matched_count < 1:
            raise APIConflictException('Item already exists in list.')
        return result

    def _update_el(self, _id, query_params, payload, exclude_params):
        log.debug('query_params {}'.format(query_params))
        log.debug('payload {}'.format(payload))
        mod_elem = {}
        for k,v in payload.items():
            mod_elem[self.list_name + '.$.' + k] = v
        query = {'_id': _id }
        if exclude_params is None:
            query[self.list_name] = {'$elemMatch': query_params}
        else:
            query['$and'] = [
                {self.list_name: {'$elemMatch': query_params}},
                {self.list_name: {'$not': {'$elemMatch': exclude_params} }}
            ]
        update = {
            '$set': mod_elem
        }
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        return self.dbc.update_one(query, update)

    def _delete_el(self, _id, query_params):
        log.debug('query_params {}'.format(query_params))
        query = {'_id': _id}
        update = {'$pull': {self.list_name: query_params} }
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        result =  self.dbc.update_one(query, update)
        if self.list_name is 'files' and self.cont_name in ['sessions', 'acquisitions']:
            if self.cont_name == 'sessions':
                session_id = _id
            else:
                session_id = AcquisitionStorage().get_container(_id).get('session')
            SessionStorage().recalc_session_compliance(session_id)
        return result

    def _get_el(self, _id, query_params):
        log.debug('query_params {}'.format(query_params))
        query = {'_id': _id, self.list_name: {'$elemMatch': query_params}}
        projection = {self.list_name + '.$': 1}
        log.debug('query {}'.format(query))
        log.debug('projection {}'.format(projection))
        result = self.dbc.find_one(query, projection)
        if result and result.get(self.list_name):
            return result.get(self.list_name)[0]


class StringListStorage(ListStorage):
    """
    This class provides access to string sublists of a mongodb collections elements (called containers).
    The difference with other sublists is that the elements are not object but strings.
    """

    def get_container(self, _id, query_params=None):
        if self.dbc is None:
            raise RuntimeError('collection not initialized before calling get_container')
        if self.use_object_id:
            try:
                _id = bson.objectid.ObjectId(_id)
            except bson.errors.InvalidId as e:
                raise APIStorageException(e.message)
        query = {'_id': _id}
        projection = {self.list_name : 1, 'permissions': 1, 'public': 1, 'roles': 1}
        return self.dbc.find_one(query, projection)

    def exec_op(self, action, _id=None, query_params=None, payload=None, exclude_params=None):
        """
        This method "flattens" the query parameter and the payload to handle string lists
        """
        if query_params is not None:
            query_params = query_params['value']
        if payload is not None:
            payload = payload.get('value')
            if payload is None:
                raise ValueError('payload Key "value" should be defined')
        return super(StringListStorage, self).exec_op(action, _id, query_params, payload, exclude_params)

    def _create_el(self, _id, payload, exclude_params):
        log.debug('payload {}'.format(payload))
        query = {'_id': _id, self.list_name: {'$ne': payload}}
        update = {'$push': {self.list_name: payload}}
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        result = self.dbc.update_one(query, update)
        if result.matched_count < 1:
            raise APIConflictException('Item already exists in list.')
        return result

    def _update_el(self, _id, query_params, payload, exclude_params):
        log.debug('query_params {}'.format(payload))
        log.debug('payload {}'.format(query_params))
        query = {
            '_id': _id,
            '$and':[
                {self.list_name: query_params},
                {self.list_name: {'$ne': payload} }
            ]
        }
        update = {'$set': {self.list_name + '.$': payload}}
        log.debug('query {}'.format(query))
        log.debug('update {}'.format(update))
        return self.dbc.update_one(query, update)

    def _get_el(self, _id, query_params):
        log.debug('query_params {}'.format(query_params))
        query = {'_id': _id, self.list_name: query_params}
        projection = {self.list_name + '.$': 1}
        log.debug('query {}'.format(query))
        log.debug('projection {}'.format(projection))
        result = self.dbc.find_one(query, projection)
        if result and result.get(self.list_name):
            return result.get(self.list_name)[0]


class AnalysesStorage(ListStorage):

    def get_fileinfo(self, _id, analysis_id, filename = None):
        _id = bson.ObjectId(_id)
        analysis = self._get_el(_id, {'_id': analysis_id})
        if analysis is None:
            raise APIStorageException('{} {} not found in {} {}.'.format(self.list_name, analysis_id, self.cont_name, _id))
        files = analysis.get('files')
        if files is None:
            return None
        if filename:
            for f in files:
                if f.get('name') == filename:
                    return [f]
        else:
            return files

    def add_note(self, _id, analysis_id, payload):
        _id = bson.ObjectId(_id)
        query = {
            '_id': _id,
            'analyses._id': analysis_id
        }
        update = {
            '$push': {
                'analyses.$.notes': payload
            }
        }
        return self.dbc.update_one(query, update)

    def delete_note(self, _id, analysis_id, note_id):
        _id = bson.ObjectId(_id)
        query = {
            '_id': _id,
            'analyses._id': analysis_id
        }
        update = {
            '$pull': {
                'analyses.$.notes': {
                    '_id': note_id
                }
            }
        }
        return self.dbc.update_one(query, update)

    @staticmethod
    def default_analysis(origin):
        analysis_obj = {}
        analysis_obj['_id'] = str(bson.objectid.ObjectId())
        analysis_obj['created'] = datetime.datetime.utcnow()
        analysis_obj['modified'] = datetime.datetime.utcnow()
        analysis_obj['user'] = origin.get('id')

        return analysis_obj


    def create_job_and_analysis(self, cont_name, cid, analysis, job, origin):
        """
        Create and insert job and analysis.
        """

        cid = bson.objectid.ObjectId(cid)

        default = self.default_analysis(origin)
        default.update(analysis)
        analysis = default

        # Save inputs to analysis and job
        inputs = {} # For Job object (map of FileReferences)
        files = [] # For Analysis object (list of file objects)
        for x in job['inputs'].keys():
            input_map = job['inputs'][x]
            fileref = create_filereference_from_dictionary(input_map)
            inputs[x] = fileref

            contref = create_containerreference_from_filereference(fileref)
            file_ = contref.find_file(fileref.name)
            if file_:
                file_.pop('output', None) # If file was from an analysis
                file_['input'] = True
                files.append(file_)
        analysis['files'] = files

        result = self._create_el(cid, analysis, None)
        if result.modified_count != 1:
            raise APIStorageException('Element not added in list analyses of container {} {}'.format(cont_name, cid))

        # Prepare job
        tags = job.get('tags', [])
        if 'analysis' not in tags:
            tags.append('analysis')

        gear_id = job['gear_id']

        # Config manifest check
        gear = get_gear(gear_id)
        if gear.get('gear', {}).get('custom', {}).get('flywheel', {}).get('invalid', False):
            raise APIConflictException('Gear marked as invalid, will not run!')
        validate_gear_config(gear, job.get('config'))

        destination = create_containerreference_from_dictionary({'type': 'analysis', 'id': analysis['_id']})

        job = Job(gear_id, inputs, destination=destination, tags=tags, config_=job.get('config'), origin=origin)
        job_id = job.insert()

        if not job_id:
            raise APIStorageException(500, 'Job not created for analysis {} of container {} {}'.format(analysis['_id'], cont_name, cid))

        result = self._update_el(cid, {'_id': analysis['_id']}, {'job': job_id}, None)
        return { 'analysis': analysis, 'job_id':job_id, 'job': job}

    @staticmethod
    def inflate_job_info(analysis):
        """
        Inflate job from id ref in analysis

        Lookup job via id stored on analysis
        Lookup input filerefs and inflate into files array with 'input': True
        If job is in failed state, look for most recent job referencing this analysis
        Update analysis if new job is found
        """

        if analysis.get('job') is None:
            return analysis
        try:
            job = Job.get(analysis['job'])
        except:
            raise Exception('No job with id {} found.'.format(analysis['job']))

        # If the job currently tied to the analysis failed, try to find one that didn't
        while job.state == 'failed' and job.id_ is not None:
            next_job = config.db.jobs.find_one({'previous_job_id': job.id_})
            if next_job is None:
                break
            job = Job.load(next_job)
        if job.id_ != str(analysis['job']):
            # Update analysis if job has changed
            # Remove old inputs and replace with new job inputs
            # (In practice these should never change)
            files = analysis.get('files', [])
            files[:] = [x for x in files if x.get('output')]

            for i in getattr(job, 'inputs',{}):
                fileref = job.inputs[i]
                contref = containerutil.create_containerreference_from_filereference(job.inputs[i])
                file_ = contref.find_file(fileref.name)
                if file_:
                    file_['input'] = True
                    files.append(file_)

            q = {'analyses._id': analysis['_id']}
            u = {'$set': {'analyses.$.job': job.id_, 'analyses.$.files': files}}
            config.db.sessions.update_one(q, u)

        analysis['job'] = job
        return analysis


class FileStorage(ListStorage):

    def update_file(self, _id, query_params, payload, replace_fields=False):
        mod_elem = {}
        update = {}

        # If we want to add to the classification lists rather than replace
        # the entirity of the classification map, use $addToSet.
        # This allows some endpoints to only make additive changes
        if not replace_fields:
            classification = payload.pop('classification', None)
            if classification:
                add_to_set = {}
                for k,array in classification.items():
                    add_to_set[self.list_name + '.$.classification.' + k] = array
                update['$addToSet'] = add_to_set
            payload = util.mongo_dict(payload)

        for k,v in payload.items():
            mod_elem[self.list_name + '.$.' + k] = v
        query = {
            '_id': _id,
            self.list_name: {'$elemMatch': query_params}
        }
        update['$set'] = mod_elem

        return self.dbc.update_one(query, update)
