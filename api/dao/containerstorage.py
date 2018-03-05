import datetime

import bson
import copy

from . import containerutil
from . import hierarchy
from .. import config

from ..jobs.jobs import Job
from ..jobs.queue import Queue
from ..jobs.rules import copy_site_rules_for_project
from ..web.errors import APIStorageException, APINotFoundException
from .basecontainerstorage import ContainerStorage

log = config.log


class GroupStorage(ContainerStorage):

    def __init__(self):
        super(GroupStorage,self).__init__('groups', use_object_id=False)

    def _fill_default_values(self, cont):
        cont = super(GroupStorage,self)._fill_default_values(cont)
        if cont:
            if 'permissions' not in cont:
                cont['permissions'] = []
        return cont

    def create_el(self, payload):
        permissions = payload.pop('permissions')
        return self.dbc.update_one(
            {'_id': payload['_id']},
            {
                '$set': payload,
                '$setOnInsert': {'permissions': permissions}
            },
            upsert=True)


class ProjectStorage(ContainerStorage):

    def __init__(self):
        super(ProjectStorage,self).__init__('projects', use_object_id=True, use_delete_tag=True)

    def create_el(self, payload):
        result = super(ProjectStorage, self).create_el(payload)
        copy_site_rules_for_project(result.inserted_id)
        return result

    def update_el(self, _id, payload, unset_payload=None, recursive=False, r_payload=None, replace_metadata=False):
        result = super(ProjectStorage, self).update_el(_id, payload, unset_payload=unset_payload, recursive=recursive, r_payload=r_payload, replace_metadata=replace_metadata)

        if result.modified_count < 1:
            raise APINotFoundException('Could not find project {}'.format(_id))

        if payload and 'template' in payload:
            # We are adding/changing the project template, update session compliance
            sessions = self.get_children(_id, projection={'_id':1})
            session_storage = SessionStorage()
            for s in sessions:
                session_storage.update_el(s['_id'], {'project_has_template': True})

        elif unset_payload and 'template' in unset_payload:
            # We are removing the project template, remove session compliance
            sessions = self.get_children(_id, projection={'_id':1})
            session_storage = SessionStorage()
            for s in sessions:
                session_storage.update_el(s['_id'], None, unset_payload={'project_has_template': '', 'satisfies_template': ''})

        return result

    def recalc_sessions_compliance(self, project_id=None):
        if project_id is None:
            # Recalc all projects
            projects = self.get_all_el({'template': {'$exists': True}}, None, None)
        else:
            project = self.get_container(project_id)
            if project:
                projects = [project]
            else:
                raise APINotFoundException('Could not find project {}'.format(project_id))
        changed_sessions = []

        for project in projects:
            template = project.get('template',{})
            if not template:
                continue
            else:
                session_storage = SessionStorage()
                sessions = session_storage.get_all_el({'project': project['_id']}, None, None)
                for s in sessions:
                    changed = session_storage.recalc_session_compliance(s['_id'], session=s, template=template, hard=True)
                    if changed:
                        changed_sessions.append(s['_id'])
        return changed_sessions


class SessionStorage(ContainerStorage):

    def __init__(self):
        super(SessionStorage,self).__init__('sessions', use_object_id=True, use_delete_tag=True)

    def _fill_default_values(self, cont):
        cont = super(SessionStorage,self)._fill_default_values(cont)
        if cont:
            s_defaults = {'analyses': [], 'subject':{}}
            s_defaults.update(cont)
            cont = s_defaults
        return cont

    def create_el(self, payload):
        project = ProjectStorage().get_container(payload['project'])
        if project.get('template'):
            payload['project_has_template'] = True
            payload['satisfies_template'] = hierarchy.is_session_compliant(payload, project.get('template'))
        return super(SessionStorage, self).create_el(payload)

    def update_el(self, _id, payload, unset_payload=None, recursive=False, r_payload=None, replace_metadata=False):
        session = self.get_container(_id)
        if session is None:
            raise APINotFoundException('Could not find session {}'.format(_id))

        # If the subject code is changed, change the subject id to either
        # the Id of the new subject code if there is another session in the same project
        # that has that subject code or a new Id
        if payload and payload.get('subject',{}).get('code') and payload.get('subject', {}).get('code') != session.get('subject', {}).get('code'):
            sibling_session = self.dbc.find_one({'project': session.get('project'), 'subject.code': payload.get('subject', {}).get('code')})
            if sibling_session:
                payload['subject']['_id'] = sibling_session.get('subject').get('_id')
            else:
                payload['subject']['_id'] = bson.ObjectId()

        # Determine if we need to calc session compliance
        # First check if project is being changed
        if payload and payload.get('project'):
            project = ProjectStorage().get_container(payload['project'])
            if not project:
                raise APINotFoundException("Could not find project {}".format(payload['project']))
        else:
            project = ProjectStorage().get_container(session['project'])

        # Check if new (if project is changed) or current project has template
        payload_has_template = project.get('template', False)
        session_has_template = session.get('project_has_template') is not None
        unset_payload_has_template = (unset_payload and 'project_has_template'in unset_payload)

        if payload_has_template or (session_has_template and not unset_payload_has_template):
            session.update(payload)
            if project and project.get('template'):
                payload['project_has_template'] = True
                payload['satisfies_template'] = hierarchy.is_session_compliant(session, project.get('template'))
            elif project:
                if not unset_payload:
                    unset_payload = {}
                unset_payload['satisfies_template'] = ""
                unset_payload['project_has_template'] = ""
        return super(SessionStorage, self).update_el(_id, payload, unset_payload=unset_payload, recursive=recursive, r_payload=r_payload, replace_metadata=replace_metadata)

    def recalc_session_compliance(self, session_id, session=None, template=None, hard=False):
        """
        Calculates a session's compliance with the project's session template.
        Returns True if the status changed, False otherwise
        """
        if session is None:
            session = self.get_container(session_id)
        if session is None:
            raise APINotFoundException('Could not find session {}'.format(session_id))
        if hard:
            # A "hard" flag will also recalc if session is tracked by a project template
            project = ProjectStorage().get_container(session['project'])
            project_has_template = bool(project.get('template'))
            if session.get('project_has_template', False) != project_has_template:
                if project_has_template == True:
                    self.update_el(session['_id'], {'project_has_template': True})
                else:
                    self.update_el(session['_id'], None, unset_payload={'project_has_template': '', 'satisfies_template': ''})
                return True
        if session.get('project_has_template'):
            if template is None:
                template = ProjectStorage().get_container(session['project']).get('template')
            satisfies_template = hierarchy.is_session_compliant(session, template)
            if session.get('satisfies_template') != satisfies_template:
                update = {'satisfies_template': satisfies_template}
                super(SessionStorage, self).update_el(session_id, update)
                return True
        return False

    def get_all_for_targets(self, target_type, target_ids, user=None, projection=None):
        """
        Given a container type and list of ids, get all sessions that are in those hierarchies.

        For example, if target_type='projects' and target_ids=['id1', 'id2'], this method will return
        all sessions that are in project id1 and project id2.

        Params `target_ids` and `collection`

        If user is supplied, will only return sessions with user in its perms list.
        If projection is supplied, it will be applied to the session query.
        """

        query = {}
        target_type = containerutil.singularize(target_type)

        if target_type == 'project':
            query['project'] = {'$in':target_ids}

        elif target_type == 'session':
            query['_id'] = {'$in':target_ids}

        elif target_type == 'acquisition':
            a_query = copy.deepcopy(query)
            a_query['_id'] = {'$in':target_ids}
            session_ids = list(set([a['session'] for a in AcquisitionStorage().get_all_el(a_query, user, {'session':1})]))
            query['_id'] = {'$in':session_ids}

        else:
            raise ValueError('Cannot get all sessions from target container {}'.format(target_type))

        return self.get_all_el(query, user, projection)



class AcquisitionStorage(ContainerStorage):

    def __init__(self):
        super(AcquisitionStorage,self).__init__('acquisitions', use_object_id=True, use_delete_tag=True)

    def create_el(self, payload):
        result = super(AcquisitionStorage, self).create_el(payload)
        SessionStorage().recalc_session_compliance(payload['session'])
        return result

    def update_el(self, _id, payload, unset_payload=None, recursive=False, r_payload=None, replace_metadata=False):
        result = super(AcquisitionStorage, self).update_el(_id, payload, unset_payload=unset_payload, recursive=recursive, r_payload=r_payload, replace_metadata=replace_metadata)
        acquisition = self.get_container(_id)
        if acquisition is None:
            raise APINotFoundException('Could not find acquisition {}'.format(_id))
        SessionStorage().recalc_session_compliance(acquisition['session'])
        return result

    def delete_el(self, _id):
        acquisition = self.get_container(_id)
        if acquisition is None:
            raise APINotFoundException('Could not find acquisition {}'.format(_id))
        result = super(AcquisitionStorage, self).delete_el(_id)
        SessionStorage().recalc_session_compliance(acquisition['session'])
        return result

    def get_all_for_targets(self, target_type, target_ids, user=None, projection=None, collection_id=None):
        """
        Given a container type and list of ids, get all acquisitions that are in those hierarchies.

        For example, if target_type='projects' and target_ids=['id1', 'id2'], this method will return
        all acquisitions that are in sessions in project id1 and project id2.

        Params `target_ids` and `collection`

        If user is supplied, will only return acquisitions with user in its perms list.
        If projection is supplied, it will be applied to the acquisition query.
        If colllection is supplied, the collection context will be used to query acquisitions.
        """

        query = {}

        # If target_type is 'acquisitions', it just wraps self.get_all_el with a query containing
        # all acquisition ids.
        if target_type in ['acquisition', 'acquisitions']:
            query['_id'] = {'$in':target_ids}
            return self.get_all_el(query, user, projection)

        # Find session ids from projects
        session_ids = None
        if target_type in ['project', 'projects']:
            query['project'] = {'$in':target_ids}
            session_ids = [s['_id'] for s in SessionStorage().get_all_el(query, user, {'_id':1})]
        elif target_type in ['session', 'sessions']:
            session_ids = target_ids
        else:
            raise ValueError('Target type must be of type project, session or acquisition.')

        # Using session ids, find acquisitions
        query.pop('project', None)
        query['session'] = {'$in':session_ids}
        if collection_id:
            query['collections'] = collection_id
        return self.get_all_el(query, user, projection)


class CollectionStorage(ContainerStorage):

    def __init__(self):
        super(CollectionStorage, self).__init__('collections', use_object_id=True, use_delete_tag=True)


class AnalysisStorage(ContainerStorage):

    def __init__(self):
        super(AnalysisStorage, self).__init__('analyses', use_object_id=True, use_delete_tag=True)


    def get_parent(self, parent_type, parent_id):
        parent_storage = ContainerStorage.factory(parent_type)
        return parent_storage.get_container(parent_id)


    def get_analyses(self, parent_type, parent_id, inflate_job_info=False):
        parent_type = containerutil.singularize(parent_type)
        parent_id = bson.ObjectId(parent_id)
        analyses = self.get_all_el({'parent.type': parent_type, 'parent.id': parent_id}, None, None)
        if inflate_job_info:
            for analysis in analyses:
                self.inflate_job_info(analysis)
        return analyses


    def fill_values(self, analysis, cont_name, cid, origin):
        parent = self.get_parent(cont_name, cid)
        defaults = {
            'parent': {
                'type': containerutil.singularize(cont_name),
                'id': bson.ObjectId(cid)
            },
            '_id': bson.ObjectId(),
            'created': datetime.datetime.utcnow(),
            'modified': datetime.datetime.utcnow(),
            'user': origin.get('id'),
            'permissions': parent['permissions'],
        }
        for key in defaults:
            analysis.setdefault(key, defaults[key])
        if 'public' in parent:
            analysis.setdefault('public', parent['public'])


    def create_job_and_analysis(self, cont_name, cid, analysis, job, origin, uid):
        """
        Create and insert job and analysis.
        """

        self.fill_values(analysis, cont_name, cid, origin)

        # Save inputs to analysis and job
        inputs = {} # For Job object (map of FileReferences)
        files = [] # For Analysis object (list of file objects)
        for x in job.get('inputs', {}).keys():
            input_map = job['inputs'][x]
            fileref = containerutil.create_filereference_from_dictionary(input_map)
            inputs[x] = fileref

            contref = containerutil.create_containerreference_from_filereference(fileref)
            file_ = contref.find_file(fileref.name)
            if file_:
                file_.pop('output', None) # If file was from an analysis
                file_['input'] = True
                files.append(file_)
        analysis['files'] = files

        result = self.create_el(analysis)
        if not result.acknowledged:
            raise APIStorageException('Analysis not created for container {} {}'.format(cont_name, cid))

        # Prepare job
        job['destination'] = {'type': 'analysis', 'id': str(analysis['_id'])}

        tags = job.get('tags', [])
        if 'analysis' not in tags:
            tags.append('analysis')
            job['tags'] = tags

        try:

            job = Queue.enqueue_job(job, origin, perm_check_uid=uid)
            job.insert()
        except Exception as e:
            # NOTE #775 remove unusable analysis - until jobs have a 'hold' state
            self.delete_el(analysis['_id'])
            raise e

        result = self.update_el(analysis['_id'], {'job': job.id_}, None)
        return {'analysis': analysis, 'job_id': job.id_, 'job': job}


    def inflate_job_info(self, analysis):
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
        if job.id_ != analysis['job']:
            # Update analysis if job has changed
            self.update_el(analysis['_id'], {'job': job.id_})

        analysis['job'] = job
        return analysis
