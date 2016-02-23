import os
import copy
import jsonschema

from . import config

log = config.log

# following https://github.com/Julian/jsonschema/issues/98
# json schema files are expected to be in the schemas folder relative to this module
schema_path = os.path.abspath(os.path.dirname(__file__))

resolver_input = jsonschema.RefResolver('file://' + schema_path + '/schemas/input/', None)
resolver_mongo = jsonschema.RefResolver('file://' + schema_path + '/schemas/mongo/', None)

expected_mongo_schemas = set([
    'acquisition.json',
    'collection.json',
    'container.json',
    'file.json',
    'group.json',
    'note.json',
    'permission.json',
    'project.json',
    'session.json',
    'subject.json',
    'user.json',
    'avatars.json',
    'tag.json'
])
expected_input_schemas = set([
    'acquisition.json',
    'collection.json',
    'container.json',
    'file.json',
    'group.json',
    'note.json',
    'permission.json',
    'project.json',
    'session.json',
    'subject.json',
    'user.json',
    'avatars.json',
    'download.json',
    'tag.json',
    'enginemetadata.json',
    'uploader.json',
    'reaper.json'
])
mongo_schemas = set()
input_schemas = set()
# validate and cache schemas at start time
for schema_file in os.listdir(schema_path + '/schemas/mongo/'):
    mongo_schemas.add(schema_file)
    resolver_mongo.resolve(schema_file)

assert mongo_schemas == expected_mongo_schemas, '{} is different from {}'.format(mongo_schemas, expected_mongo_schemas)

for schema_file in os.listdir(schema_path + '/schemas/input/'):
    input_schemas.add(schema_file)
    resolver_input.resolve(schema_file)

assert input_schemas == expected_input_schemas, '{} is different from {}'.format(input_schemas, expected_input_schemas)

def _validate_json(json_data, schema, resolver):
    jsonschema.validate(json_data, schema, resolver=resolver)
    #jsonschema.Draft4Validator(schema, resolver=resolver).validate(json_data)

def no_op(g, *args):
    return g

def mongo_from_schema_file(handler, schema_file):
    if schema_file is None:
        return no_op
    schema = resolver_mongo.resolve(schema_file)[1]
    def g(exec_op):
        def mongo_val(method, **kwargs):
            payload = kwargs['payload']
            log.debug(payload)
            if method == 'PUT' and schema.get('required'):
                _schema = copy.copy(schema)
                _schema.pop('required')
            else:
                _schema = schema
            if method in ['POST', 'PUT']:
                try:
                    _validate_json(payload, _schema, resolver_mongo)
                except jsonschema.ValidationError as e:
                    handler.abort(500, str(e))
            return exec_op(method, **kwargs)
        return mongo_val
    return g

def payload_from_schema_file(handler, schema_file):
    if schema_file is None:
        return no_op
    schema = resolver_input.resolve(schema_file)[1]
    def g(payload, method):
        if method == 'PUT' and schema.get('required'):
            _schema = copy.copy(schema)
            _schema.pop('required')
        else:
            _schema = schema
        if method in ['POST', 'PUT']:
            try:
                _validate_json(payload, _schema, resolver_input)
            except jsonschema.ValidationError as e:
                handler.abort(400, str(e))
    return g

def key_check(handler, schema_file):
    """
    for sublists of mongo container there is no automatic key check when creating, updating or deleting an object.
    We are adding a custom array field to the json schemas ("key_fields").
    The uniqueness is checked on the combination of all the elements of "key_fields".

    For an example check api/schemas/input/permission.json:
    The key fields are the _id and the site. Uniqueness is checked on the combination
    of the values of the _id and the site of the permissions.

    So this method ensures that:
    1. after a POST and PUT request we don't have two items with the same values for the key set
    2. a GET will retrieve a single item
    3. a DELETE (most importantly) will delete a single item
    """
    if schema_file is None:
        return no_op
    schema = resolver_mongo.resolve(schema_file)[1]
    log.debug(schema)
    if schema.get('key_fields') is None:
        return no_op
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            if method == 'POST':
                try:
                    exclude_params = _post_exclude_params(schema.get('key_fields', []), payload)
                except KeyError as e:
                    handler.abort(400, 'missing key {} in payload'.format(e.args))
            else:
                _check_query_params(schema.get('key_fields'), query_params)
                if method == 'PUT' and schema.get('key_fields'):
                    exclude_params = _put_exclude_params(schema['key_fields'], query_params, payload)
            return exec_op(method, _id=_id, query_params=query_params, payload=payload, exclude_params=exclude_params)
        return f
    return g

def _put_exclude_params(keys, query_params, payload):
    exclude_params = None
    _eqp = {}
    for k in keys:
        value_p = payload.get(k)
        if value_p and value_p != query_params.get(k):
            _eqp[k] = value_p
            exclude_params = _eqp
        else:
            _eqp[k] = query_params.get(k)
    return exclude_params

def _post_exclude_params(keys, payload):
    return {
        k: payload[k] for k in keys
    }

def _check_query_params(keys, query_params):
    set_keys = set(keys)
    set_query_params_keys = set(query_params.keys())
    assert set(keys) == set(query_params.keys()), """
    {}
    is different from expected:
    {}
    """.format(query_params.keys(), keys)
