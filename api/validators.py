import copy
import json
import jsonschema
import os

from . import config

log = config.log

class InputValidationException(Exception):
    pass

class DBValidationException(Exception):
    pass

def validate_data(data, schema_json, schema_type, verb, optional=False):
    """
    Convenience method to validate a JSON schema against some action.

    If optional is set, validate_data won't complain about null data.
    """

    if optional and data is None:
        return

    suri = schema_uri(schema_type, schema_json)
    validator = from_schema_path(suri)
    validator(data, verb)

def _validate_json(json_data, schema, resolver):
    jsonschema.validate(json_data, schema, resolver=resolver, format_checker=jsonschema.FormatChecker())

# We store the resolvers for each base_uri we use, so that we reuse the schemas cached by the resolvers.
resolvers = {}
def _resolve_schema(schema_file_uri):
    if not resolvers.get(schema_file_uri):
        with open(schema_file_uri) as schema_file:
            base_uri = os.path.dirname(schema_file_uri)
            schema = json.load(schema_file)
            resolver = jsonschema.RefResolver('file://'+base_uri+'/', schema)
            resolvers[schema_file_uri] = (schema, resolver)
    return resolvers[schema_file_uri]

def no_op(g, *args): # pylint: disable=unused-argument
    return g

def schema_uri(type_, schema_name):
    return os.path.join(
        config.get_item('persistent', 'schema_path'),
        type_,
        schema_name
    )

def decorator_from_schema_path(schema_url):
    if schema_url is None:
        return no_op
    schema, resolver = _resolve_schema(schema_url)
    def g(exec_op):
        def validator(method, **kwargs):
            payload = kwargs['payload']
            log.debug(payload)
            if method == 'PUT' and schema.get('required'):
                _schema = copy.copy(schema)
                _schema.pop('required')
            else:
                _schema = schema
            if method in ['POST', 'PUT']:
                try:
                    _validate_json(payload, _schema, resolver)
                except jsonschema.ValidationError as e:
                    raise DBValidationException(str(e))
            return exec_op(method, **kwargs)
        return validator
    return g

def from_schema_path(schema_url):
    if schema_url is None:
        return no_op
    # split the url in base_uri and schema_name
    schema, resolver = _resolve_schema(schema_url)
    def g(payload, method):
        if method == 'PUT' and schema.get('required'):
            _schema = copy.copy(schema)
            _schema.pop('required')
        else:
            _schema = schema
        if method in ['POST', 'PUT']:
            try:
                _validate_json(payload, _schema, resolver)
            except jsonschema.ValidationError as e:
                raise InputValidationException(str(e))
    return g

def key_check(schema_url):
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
    if schema_url is None:
        return no_op
    schema, _ = _resolve_schema(schema_url)
    log.debug(schema)
    if schema.get('key_fields') is None:
        return no_op
    def g(exec_op):
        def f(method, _id, query_params = None, payload = None, exclude_params=None):
            if method == 'POST':
                try:
                    exclude_params = _post_exclude_params(schema.get('key_fields', []), payload)
                except KeyError as e:
                    raise InputValidationException('missing key {} in payload'.format(e.args))
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
    assert set(keys) == set(query_params.keys()), """
    {}
    is different from expected:
    {}
    """.format(query_params.keys(), keys)
