import datetime

from .. import base
from .. import config
from .. import debuginfo
from .. import validators
from ..auth import groupauth, always_ok
from ..dao import containerstorage

log = config.log


class GroupHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(GroupHandler, self).__init__(request, response)

    def get(self, _id):
        self._init_storage()
        group = self._get_group(_id)
        if not group:
            self.abort(404, 'no such Group: ' + _id)
        permchecker = groupauth.default(self, group)
        result = permchecker(self.storage.exec_op)('GET', _id)
        return result

    def delete(self, _id):
        if _id == 'unknown':
            self.abort(400, 'The group "unknown" can\'t be deleted as it is integral within the API')
        self._init_storage()
        group = self._get_group(_id)
        if not group:
            self.abort(404, 'no such Group: ' + _id)
        permchecker = groupauth.default(self, group)
        result = permchecker(self.storage.exec_op)('DELETE', _id)
        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'User {} not removed'.format(_id))
        return result

    def get_all(self, uid=None):
        self._init_storage()
        query = None
        projection = {'name': 1, 'created': 1, 'modified': 1}
        permchecker = groupauth.list_permission_checker(self, uid)
        results = permchecker(self.storage.exec_op)('GET', projection=projection)
        if results is None:
            self.abort(404, 'Not found')
        if self.debug:
            debuginfo.add_debuginfo(self, 'groups', results)
        return results

    def put(self, _id):
        self._init_storage()
        group = self._get_group(_id)
        if not group:
            self.abort(404, 'no such Group: ' + _id)
        permchecker = groupauth.default(self, group)
        payload = self.request.json_body
        mongo_validator = validators.mongo_from_schema_file(self, 'group.json')
        payload_validator = validators.payload_from_schema_file(self, 'group.json')
        payload_validator(payload, 'PUT')
        result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'User {} not updated'.format(_id))

    def post(self):
        self._init_storage()
        permchecker = groupauth.default(self, None)
        payload = self.request.json_body
        mongo_validator = validators.mongo_from_schema_file(self, 'group.json')
        payload_validator = validators.payload_from_schema_file(self, 'group.json')
        payload_validator(payload, 'POST')
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        payload['roles'] = [{'_id': self.uid, 'access': 'admin', 'site': self.user_site}]
        result = permchecker(mongo_validator(self.storage.exec_op))('POST', payload=payload)
        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(404, 'User {} not updated'.format(_id))

    def _init_storage(self):
        self.storage = containerstorage.ContainerStorage('groups', use_object_id=False)

    def _get_group(self, _id):
        group = self.storage.get_container(_id)
        if group is not None:
            return group
        else:
            self.abort(404, 'user {} not found'.format(_id))
