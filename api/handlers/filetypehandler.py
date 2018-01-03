import re

from .. import config
from ..auth import require_admin, require_login
from ..validators import validate_data, InputValidationException
from ..web import base


class FileType(base.RequestHandler):

    @require_login
    def get(self):
        """Get file types"""
        return config.db.filetypes.find()

    @require_admin
    def post(self):
        """
        Insert or replace a file type. Required fields: '_id' and 'regex' where the '_id' is the unique name of
        the file type and 'regex' is a regular expression which is used to figure out the file type from the file name.
        """
        payload = self.request.json_body
        validate_data(payload, 'filetype.json', 'input', 'POST')
        try:
            re.compile(payload['regex'])
        except re.error:
            raise InputValidationException('Invalid regular expression')
        result = config.db.filetypes.replace_one({'_id': payload['_id']}, payload, upsert=True)
        if result.acknowledged:
            _id = result.upserted_id if result.upserted_id else payload['_id']
            return {'_id': _id}
        else:
            self.abort(404, 'File type {} not updated'.format(payload['_id']))

    @require_admin
    def delete(self, _id):
        """Delete a file type"""
        result = config.db.filetypes.delete_one({'_id': _id})
        if result.deleted_count:
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'File type {} not removed'.format(_id))
