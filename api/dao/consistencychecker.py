"""Scope of this module is to define consistency checkers that will
do some verification against the database before allowing the operation"""

from .. import config
from . import APIConsistencyException

def noop(*args, **kwargs): # pylint: disable=unused-argument
    pass

def get_list_storage_checker(action, list_name):
    """Build the checker for the list storage"""
    if list_name == ['permissions', 'roles'] and action == 'POST':
        return user_on_permission
    return noop

def get_container_storage_checker(action, cont_name):
    """Build the checker for the container storage"""
    if cont_name == 'projects' and action in ['PUT', 'POST']:
        return field_on_container('session', 'sessions')
    elif cont_name == 'sessions' and action in ['PUT', 'POST']:
        return field_on_container('project', 'projects')
    elif cont_name == 'acquisitions' and action in ['PUT', 'POST']:
        return field_on_container('acquisition', 'acquisitions')
    elif cont_name == 'groups' and action == 'DELETE':
        return check_children('group', 'projects')
    elif cont_name == 'projects' and action == 'DELETE':
        return check_children('project', 'sessions')
    elif cont_name == 'sessions' and action == 'DELETE':
        return check_children('session', 'acquisitions')
    return noop

def user_on_permission(data_op, **kwargs): # pylint: disable=unused-argument
    """Check that for a permission the user already exists.

    Used before PUT operations.
    """
    if data_op['site'] == config.get_item('site', 'id'):
        if not config.db.users.find_one({'_id': data_op['_id']}):
            raise APIConsistencyException('user does not exist')

def field_on_container(parent_field, parent_container_name):
    """Checks that if we are moving or creating a container,
    the new parent container already exists.

    Used before POST/PUT operations.
    """
    def f(data_op, **kwargs): # pylint: disable=unused-argument
        if data_op.get(parent_field) and not config.db[parent_container_name].find_one({'_id': data_op[parent_field]}):
            raise APIConsistencyException('{} {} does not exist'.format(parent_field, data_op[parent_field]))
    return f

def check_children(foreign_key_field, container_name):
    """Check that a container has no children.

    Used before DELETE operations.

    Args:
        foreign_key_field (str): key field name in container_name collection
        container_name (str): db collection to search

    Returns:
        None:

    Raises:
        APIConsistencyException: Child document found
    """
    def f(data_op, **kwargs): # pylint: disable=unused-argument
        if config.db[container_name].find_one({foreign_key_field: data_op['_id']}):
            raise APIConsistencyException(
                'DELETE not allowed. Children {} found for {}'.format(container_name, data_op['_id'])
            )
    return f
