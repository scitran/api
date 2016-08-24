import logging

import jsonschema.exceptions
import pytest

from api import validators

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)

class StubHandler:
    def abort(iself, code, message):
        err_m = str(code) + ' ' + message
        raise Exception(err_m)

default_handler = StubHandler()

def test_payload():
    payload = {
        'files': [],
        'group': 'unknown',
        'label': 'SciTran/Testing',
        'public': False,
        'permissions': [],
        'extra_params': 'testtest'
    }
    schema_uri = validators.schema_uri("input", "project.json")
    schema, resolver = validators._resolve_schema(schema_uri)
    with pytest.raises(jsonschema.exceptions.ValidationError):
        validators._validate_json(payload, schema, resolver)
