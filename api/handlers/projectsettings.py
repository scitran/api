import bson
import datetime

from .. import config
from .. import util
from .. import validators
from ..auth import containerauth, always_ok, has_access, check_phi
from ..dao import containerstorage
from ..dao.basecontainerstorage import PARENT_MAP
from ..dao.containerutil import singularize
from ..jobs.gears import get_gear_by_name
from ..jobs.rules import validate_regexes
from ..validators import validate_data, verify_payload_exists
from ..web import base
from ..web.errors import APIPermissionException, APINotFoundException, APIValidationException
from ..web.request import log_access, AccessType



log = config.log

######## I don't think this is the right spot but util methods for phi access
CONT_STORAGE = {
    "groups": containerstorage.GroupStorage(),
    "projects": containerstorage.ProjectStorage(),
    "sessions": containerstorage.SessionStorage(),
    "acquisitions": containerstorage.AcquisitionStorage(),
    "analyses": containerstorage.AnalysisStorage(),
    "collections": containerstorage.CollectionStorage()
}

# PHI fields are limited to these fields
PHI_CANDIDATES = ['info', 'files.info', 'files.tags', 'notes', 'subject.firstname', 'subject.lastname', 'subject.sex',
                  'subject.age', 'subject.race', 'subject.ethnicity', 'subject.info', 'tags']

def get_project_id(cont_name, _id):
    if _id == "site" or cont_name == 'groups':
        return "site"
    if cont_name == "projects":
        return _id
    elif cont_name == "sessions":
        session = get_container(_id, cont_name, projection={'project':1})
        return session.get('project')
    elif cont_name == "acquisitions":
        return containerstorage.SessionStorage().get_container(get_container(_id, cont_name, projection={'session':1}).get('session'), projection={'project':1}).get('project')
    elif cont_name == "collections":
        return "site"
    else:
        raise APINotFoundException("{} are not a container".format(cont_name))

def check_phi_enabled(cont_name, _id):
    project_id = get_project_id(cont_name, _id)
    if project_id != "site":
        return get_container(project_id, "projects").get("phi")
    else:
        return True
def get_phi_fields(cont_name, _id):
    project_storage = containerstorage.ProjectStorage()
    project_id = get_project_id(cont_name, _id)
    if _id == "site" or project_id == "site":
        site_phi = project_storage.get_phi_fields("site")
        phi_fields = list(set(site_phi.get("fields",[])))
    else:
        project_phi = project_storage.get_phi_fields(project_id)
        site_phi = project_storage.get_phi_fields("site")
        phi_fields = list(set(site_phi.get("fields",[]) + project_phi.get("fields",[])))
    projection = {x:0 for x in phi_fields}
    if len(projection) == 0:
        projection = None
    return projection

def get_container(_id, cont_name, projection=None, get_children=False):
    container = CONT_STORAGE[cont_name].get_container(_id, projection=projection, get_children=get_children)
    if container is not None:
        return container
    else:
        raise APINotFoundException(404, 'Element {} not found in container {}'.format(_id, cont_name))


def phi_payload(method=None):
    def phi_payload_decorator(handler_method):
        def phi_payload_check(self, *args, **kwargs):
            if not self.superuser_request and method in ["POST", "PUT"]:
                cid = kwargs.get('cid')
                cont_name = kwargs.get('cont_name')
                if cont_name == "analyses" and self.is_true("job"):
                    payload = util.mongo_dict(self.request.json_body.get("analysis"))
                else:
                    payload = util.mongo_dict(self.request.json_body)
                self.storage = CONT_STORAGE[cont_name]
                # Check the using the parent of the container to be created
                if method == "POST":
                    cont_name = PARENT_MAP[cont_name]
                    cid = payload[singularize(cont_name)]
                if not cid or not cont_name:
                    raise APIValidationException("Request body malformed")
                phi_fields = get_phi_fields(cont_name, cid) if cont_name != "groups" else get_phi_fields("projects", "site")

                # If the request is not a superuser/has phi and one of fields in the payload is considered phi by the project the container is in, Raise a permission exception
                if not check_phi(self.uid, get_container(cid, cont_name)) and phi_fields and any([True for x in payload if x.startswith(tuple(phi_fields.keys()))]):
                    log.debug("PHI fields: " + str(phi_fields))
                    raise APIPermissionException("User not allowed to write to phi fields")
            return handler_method(self, *args, **kwargs)
        return phi_payload_check
    return phi_payload_decorator

class ProjectSettings(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(ProjectSettings, self).__init__(request, response)
        self.storage = containerstorage.ProjectStorage()

    def set_project_template(self, **kwargs):
        project_id = kwargs.pop('cid')
        container = self.storage.get_container(project_id)

        template = self.request.json_body
        validators.validate_data(template, 'project-template.json', 'input', 'POST')
        payload = {'template': template}
        payload['modified'] = datetime.datetime.utcnow()

        permchecker = self._get_permchecker(container)
        result = permchecker(self.storage.exec_op)('PUT', _id=project_id, payload=payload)
        return {'modified': result.modified_count}

    def delete_project_template(self, **kwargs):
        project_id = kwargs.pop('cid')
        container = self.storage.get_container(project_id)

        payload = {'modified': datetime.datetime.utcnow()}
        unset_payload = {'template': ''}

        permchecker = self._get_permchecker(container)
        result = permchecker(self.storage.exec_op)('PUT', _id=project_id, payload=payload, unset_payload=unset_payload)
        return {'modified': result.modified_count}

    def get_phi(self, cid):
        projection = None

        if cid == 'site':
            if self.public_request:
                raise APIPermissionException('Viewing site-level PHI fields requires login.')
            projection = {'project_id': 0}
        else:
            project = self.storage.get_container(cid, projection={'permissions': 1, 'phi': 1})
            if not self.user_is_admin and not has_access(self.uid, project, 'ro'):
                raise APIPermissionException('User does not have access to project {} PHI fields'.format(cid))
            if not project.get('phi'):
                self.abort(400, "Project {} does not have custom phi list enabled".format(project.get('_id')))

        return self.storage.get_phi_fields(cid, projection=projection)

    @log_access(AccessType.modify_phi_list)
    def update_phi(self, cid):
        payload = self.request.json_body
        if cid == 'site':
            if not self.user_is_admin:
                raise APIPermissionException('Modifying site-level PHI fields can only be done by a site admin.')
        else:
            project = self.storage.get_container(cid, projection={'permissions': 1, 'phi':1})
            if not self.user_is_admin and not has_access(self.uid, project, 'admin'):
                raise APIPermissionException('User does not have access to project {} PHI fields'.format(cid))
            if not project.get('phi'):
                self.abort(400, "Project {} does not have custom phi list enabled".format(project.get('_id')))
        if not all([x.startswith(tuple(PHI_CANDIDATES)) for x in payload["fields"]]):
            self.abort(400, "All fields to be set must be valid phi candidates")
        result = self.storage.add_phi_fields(cid, payload)
        if result['nModified'] == 1 or result.get('upserted'):
            return {"modified": result['nModified'], "upserted": result.get('upserted')}
        else:
            self.abort(404, "Unable to update phi fields for project_id:{}".format(cid))

    def _get_permchecker(self, container=None, parent_container=None):
        if self.superuser_request:
            return always_ok
        elif self.public_request:
            return containerauth.public_request(self, container)
        else:
            permchecker = containerauth.default_container
            return permchecker(self, container, parent_container)


class RulesHandler(base.RequestHandler):

    def get(self, cid):
        """List rules"""

        projection = None

        if cid == 'site':
            if self.public_request:
                raise APIPermissionException('Viewing site-level rules requires login.')
            projection = {'project_id': 0}
        else:
            project = containerstorage.ProjectStorage().get_container(cid, projection={'permissions': 1})
            if not self.user_is_admin and not has_access(self.uid, project, 'ro'):
                raise APIPermissionException('User does not have access to project {} rules'.format(cid))

        return config.db.project_rules.find({'project_id' : cid}, projection=projection)


    @verify_payload_exists
    def post(self, cid):
        """Add a rule"""

        if cid == 'site':
            if not self.user_is_admin:
                raise APIPermissionException('Adding site-level rules can only be done by a site admin.')
        else:
            project = containerstorage.ProjectStorage().get_container(cid, projection={'permissions': 1})
            if not self.user_is_admin and not has_access(self.uid, project, 'admin'):
                raise APIPermissionException('Adding rules to a project can only be done by a project admin.')

        doc = self.request.json

        validate_data(doc, 'rule-new.json', 'input', 'POST', optional=True)
        validate_regexes(doc)
        try:
            get_gear_by_name(doc['alg'])
        except APINotFoundException:
            self.abort(400, 'Cannot find gear for alg {}, alg not valid'.format(doc['alg']))

        doc['project_id'] = cid

        result = config.db.project_rules.insert_one(doc)
        return { '_id': result.inserted_id }

class RuleHandler(base.RequestHandler):

    def get(self, cid, rid):
        """Get rule"""

        projection = None
        if cid == 'site':
            if self.public_request:
                raise APIPermissionException('Viewing site-level rules requires login.')
            projection = {'project_id': 0}
        else:
            project = containerstorage.ProjectStorage().get_container(cid, projection={'permissions': 1})
            if not self.user_is_admin and not has_access(self.uid, project, 'ro'):
                raise APIPermissionException('User does not have access to project {} rules'.format(cid))

        result = config.db.project_rules.find_one({'project_id' : cid, '_id': bson.ObjectId(rid)}, projection=projection)

        if not result:
            raise APINotFoundException('Rule not found.')

        return result


    @verify_payload_exists
    def put(self, cid, rid):
        """Change a rule"""

        if cid == 'site':
            if not self.user_is_admin:
                raise APIPermissionException('Modifying site-level rules can only be done by a site admin.')
        else:
            project = containerstorage.ProjectStorage().get_container(cid, projection={'permissions': 1})
            if not self.user_is_admin and not has_access(self.uid, project, 'admin'):
                raise APIPermissionException('Modifying project rules can only be done by a project admin.')

        doc = config.db.project_rules.find_one({'project_id' : cid, '_id': bson.ObjectId(rid)})

        if not doc:
            raise APINotFoundException('Rule not found.')

        updates = self.request.json
        validate_data(updates, 'rule-update.json', 'input', 'POST', optional=True)
        validate_regexes(updates)
        if updates.get('alg'):
            try:
                get_gear_by_name(updates['alg'])
            except APINotFoundException:
                self.abort(400, 'Cannot find gear for alg {}, alg not valid'.format(updates['alg']))

        doc.update(updates)
        config.db.project_rules.replace_one({'_id': bson.ObjectId(rid)}, doc)

        return


    def delete(self, cid, rid):
        """Remove a rule"""

        if cid == 'site':
            if not self.user_is_admin:
                raise APIPermissionException('Modifying site-level rules can only be done by a site admin.')
        else:
            project = containerstorage.ProjectStorage().get_container(cid, projection={'permissions': 1})
            if not self.user_is_admin and not has_access(self.uid, project, 'admin'):
                raise APIPermissionException('Modifying project rules can only be done by a project admin.')


        result = config.db.project_rules.delete_one({'project_id' : cid, '_id': bson.ObjectId(rid)})
        if result.deleted_count != 1:
            raise APINotFoundException('Rule not found.')
        return
