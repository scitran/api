import datetime

from ..web import base
from .. import util
from .. import validators
from ..auth import groupauth
from ..dao import containerstorage
from .containerhandler import ContainerHandler


class GroupHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(GroupHandler, self).__init__(request, response)
        self.storage = containerstorage.GroupStorage()

    def get(self, _id):
        group = self._get_group(_id)
        permchecker = groupauth.default(self, group)
        result = permchecker(self.storage.exec_op)('GET', _id)
        if not self.superuser_request and not self.is_true('join_avatars'):
            self._filter_roles([result], self.uid, self.user_site)
        if self.is_true('join_avatars'):
            ContainerHandler.join_user_info([result])
        return result

    def delete(self, _id):
        if _id == 'unknown':
            self.abort(400, 'The group "unknown" can\'t be deleted as it is integral within the API')
        group = self._get_group(_id)
        permchecker = groupauth.default(self, group)
        result = permchecker(self.storage.exec_op)('DELETE', _id)
        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'Group {} not removed'.format(_id))
        return result

    def get_all(self, uid=None):
        projection = {'name': 1, 'created': 1, 'modified': 1}
        permchecker = groupauth.list_permission_checker(self, uid)
        results = permchecker(self.storage.exec_op)('GET', projection=projection)
        if not self.superuser_request and not self.is_true('join_avatars'):
            self._filter_roles(results, self.uid, self.user_site)
        if self.is_true('join_avatars'):
            results = ContainerHandler.join_user_info(results)
        return results

    def put(self, _id):
        group = self._get_group(_id)
        permchecker = groupauth.default(self, group)
        payload = self.request.json_body
        mongo_schema_uri = validators.schema_uri('mongo', 'group.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', 'group-update.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'PUT')
        result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Group {} not updated'.format(_id))

    def post(self):
        permchecker = groupauth.default(self, None)
        payload = self.request.json_body
        mongo_schema_uri = validators.schema_uri('mongo', 'group.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = validators.schema_uri('input', 'group-new.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'POST')
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        payload['roles'] = [{'_id': self.uid, 'access': 'admin', 'site': self.user_site}] if self.uid else []
        result = mongo_validator(permchecker(self.storage.exec_op))('POST', payload=payload)
        if result.acknowledged:
            if result.upserted_id:
                return {'_id': result.upserted_id}
            else:
                self.response.status_int = 201
                return {'_id': payload['_id']}
        else:
            self.abort(404, 'Group {} not updated'.format(payload['_id']))

    def _get_group(self, _id):
        group = self.storage.get_container(_id)
        if group is not None:
            return group
        else:
            self.abort(404, 'Group {} not found'.format(_id))

    def _filter_roles(self, results, uid, site):
        """
        if the user is not admin only her role is returned.
        """
        for result in results:
            user_perm = util.user_perm(result.get('roles', []), uid, site)
            if user_perm.get('access') != 'admin':
                result['roles'] = [user_perm] if user_perm else []
        return results
