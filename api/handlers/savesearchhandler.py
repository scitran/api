import bson
from ast import literal_eval
from ..web import base
from .. import config, validators
from ..auth import require_login
from ..dao.containerstorage import SearchStorage

from ..auth import groupauth
from ..dao import noop


log = config.log
storage = SearchStorage()


def string_filters(payload):
	if payload.get('search') and payload['search'].get('filters'):
		filters = []
		for filter_ in payload['search'].get('filters',[]):
			filters.append(str(filter_))
		payload['search']['filters'] = filters
	return payload

def unstring_filters(payload):
	if payload['search'].get('filters'):
		filters= []
		for filter_ in payload['search'].get('filters',[]):
			filters.append(literal_eval(filter_))
		payload['search']['filters']= filters
	return payload

class SaveSearchHandler(base.RequestHandler):

	def __init__(self, request=None, response=None):
		super(SaveSearchHandler, self).__init__(request, response)

	@require_login
	def post(self):
		payload = self.request.json_body
		validators.validate_data(payload, 'search-input.json', 'input', 'POST')
		payload = string_filters(payload)
		payload['permissions'] = [{"_id": self.uid, "access": "admin"}]
		payload['creator'] = self.uid
		result = storage.create_el(payload)
		if result.acknowledged:
			if result.inserted_id:
				return {'_id': result.inserted_id}
		else:
			self.abort(404, 'Search not created')

	def get_all(self):
		log.debug(self.uid)
		return storage.get_all_el({}, {'_id': self.uid}, {'label': 1})

	def get(self, sid):
		result = storage.get_el(sid)
		if result is None:
			self.abort(404, 'Element {} not found'.format(sid))
		unstring_filters(result)
		return result

	def delete(self, sid):
		search = storage.get_container(sid)
		permchecker = groupauth.default(self, search)
		result = permchecker(storage.exec_op)('DELETE', sid)
		if result.deleted_count == 1:
			return {'deleted': result.deleted_count}
		else:
			self.abort(404, 'Group {} not removed'.format(sid))
		return result

	def replace_search(self, sid):
		payload = self.request.json_body
		payload = self._scrub_replace(payload)
		validators.validate_data(payload, 'search-input.json', 'input', 'POST')
		payload = string_filters(payload)
		payload['_id'] = bson.ObjectId(sid)
		search = storage.get_container(sid)
		payload['permissions'] = search['permissions']
		permchecker = groupauth.default(self, search)
		permchecker(noop)('DELETE', sid)
		result = storage.replace_el(payload)
		if result.acknowledged:
			if result.inserted_id:
				return {'_id': result.inserted_id}
		return {"hi" : "bye"}

	def _scrub_replace(self, payload):
		'''
		Function to turn a search returned from a GET to a legal post/replace
		'''
		if payload.get('_id'):
			del(payload['_id'])
		if payload.get('permissions'):
			del(payload['permissions'])
		if payload.get('creator'):
			del(payload['creator'])
		return payload

