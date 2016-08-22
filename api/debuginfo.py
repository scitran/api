child_containers = {
    'projects': 'sessions',
    'sessions': 'acquisitions',
    'groups': 'projects'
}

def add_debuginfo(handler, cont_name, response):
    if type(response) == list:
        _add_di_list(handler, cont_name, response)
    else:
        _add_di(handler, cont_name, response)

def _add_di_list(handler, cont_name, response):
    for elem in response:
        _add_di(handler, cont_name, elem)
        if cont_name == 'groups':
            elem['debug']['details'] = handler.uri_for(
                'group_details' if cont_name == 'groups' else 'cont_details',
                _id=elem['_id'],
                _full=True) + '?' + handler.request.query_string
        else:
            elem['debug']['details'] = handler.uri_for(
                'cont_details',
                cont_name=cont_name,
                cid=elem['_id'],
                _full=True) + '?' + handler.request.query_string


def _add_di(handler, cont_name, response):
    response['debug'] = {}
    if child_containers.get(cont_name):
        child_cont_name = child_containers[cont_name]

        response['debug'][child_cont_name] = handler.uri_for(
            'cont_sublist_groups' if cont_name == 'groups' else 'cont_sublist',
            par_cont_name=cont_name,
            par_id=response['_id'],
            cont_name=child_cont_name,
            _full=True) + '?' + handler.request.query_string
    if response.get('project'):
        response['debug']['project'] = handler.uri_for(
            'cont_details',
            cont_name='projects',
            cid=response['project'],
            _full=True) + '?' + handler.request.query_string
    if response.get('group'):
        response['debug']['group'] = handler.uri_for(
            'group_details',
            _id=response['group'],
            _full=True) + '?' + handler.request.query_string
