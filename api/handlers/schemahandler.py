import os
import json

from .. import base
from .. import config

class SchemaHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(SchemaHandler, self).__init__(request, response)

    def get(self, schema):
        schema_path = os.path.join(config.schema_path, schema)
        try:
            with open(schema_path, 'rU') as f:
                return json.load(f)
        except IOError as e:
            self.abort(404, str(e))
