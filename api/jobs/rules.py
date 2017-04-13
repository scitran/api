import fnmatch

from .. import config
from ..dao.containerutil import FileReference

from . import gears
from .jobs import Job

log = config.log

# {
#     '_id':        'SOME_ID',
#     'project_id': 'SOME_PROJECT',

#     Algorithm to run if both sets of rules match
#     'alg':        'my-gear-name',
#
#     At least one match from this array must succeed, or array must be empty
#     'any': [],
#
#     All matches from array must succeed, or array must be empty
#     'all': [
#         {
#             'type': 'file.type', # Match the file's type
#             'value': 'dicom'
#         },
#         {
#             'type': 'file.name', # Match a shell glob for the file name
#             'value': '*.dcm'
#         },
#         {
#             'type': 'file.measurements', # Match any of the file's measurements
#             'value': 'diffusion'
#         },
#         {
#             'type': 'container.has-type', # Match the container having any file (including this one) with this type
#             'value': 'bvec'
#         }
#     ]
# }


def get_base_rules():
    """
    Fetch the install-global gear rules from the database
    """

    # rule_doc = config.db.singletons.find_one({'_id': 'rules'}) or {}
    # return rule_doc.get('rule_list', [])
    return []

def _log_file_key_error(file_, container, error):
    log.warning('file ' + file_.get('name', '?') + ' in container ' + str(container.get('_id', '?')) + ' ' + error)

def eval_match(match_type, match_param, file_, container):
    """
    Given a match entry, return if the match succeeded.
    """

    def lower(x):
        return x.lower()


    # Match the file's type
    if match_type == 'file.type':
        try:
            return file_['type'].lower() == match_param.lower()
        except KeyError:
            _log_file_key_error(file_, container, 'has no type key')
            return False

    # Match a shell glob for the file name
    elif match_type == 'file.name':
        return fnmatch.fnmatch(file_['name'].lower(), match_param.lower())

    # Match any of the file's measurements
    elif match_type == 'file.measurements':
        try:
            if match_param:
                return match_param.lower() in map(lower, file_.get('measurements', []))
            else:
                return False
        except KeyError:
            _log_file_key_error(file_, container, 'has no measurements key')
            return False

    # Match the container having any file (including this one) with this type
    elif match_type == 'container.has-type':
        for c_file in container['files']:
            if match_param.lower() == c_file.get('type').lower():
                return True

        return False

    raise Exception('Unimplemented match type ' + match_type)

def eval_rule(rule, file_, container):
    """
    Decide if a rule should spawn a job.
    """

    # Are there matches in the 'any' set?
    must_match = len(rule.get('any', [])) > 0
    has_match = False

    for match in rule.get('any', []):
        if eval_match(match['type'], match['value'], file_, container):
            has_match = True
            break

    # If there were matches in the 'any' array and none of them succeeded
    if must_match and not has_match:
        return False

    # Are there matches in the 'all' set?
    for match in rule.get('all', []):
        if not eval_match(match['type'], match['value'], file_, container):
            return False

    return True

def queue_job_legacy(algorithm_id, input_):
    """
    Tie together logic used from the no-manifest, single-file era.
    Takes a single FileReference instead of a map.
    """

    gear = gears.get_gear_by_name(algorithm_id)

    if len(gear['gear']['inputs']) != 1:
        raise Exception("Legacy gear enqueue attempt of " + algorithm_id + " failed: must have exactly 1 input in manifest")

    input_name = gear['gear']['inputs'].keys()[0]

    inputs = {
        input_name: input_
    }

    job = Job(str(gear['_id']), inputs, tags=['auto', algorithm_id])
    return job.insert()

def find_type_in_container(container, type_):
    for c_file in container['files']:
        if type_ == c_file['type']:
            return c_file
    return None

def create_jobs(db, container, container_type, file_):
    """
    Check all rules that apply to this file, and enqueue the jobs that should be run.
    Returns the algorithm names that were queued.
    """

    job_list = []

    # Get configured rules for this project
    rules = get_rules_for_container(db, container)

    # Add hardcoded rules that cannot be removed or changed
    for hardcoded_rule in get_base_rules():
        rules.append(hardcoded_rule)

    for rule in rules:

        if eval_rule(rule, file_, container):

            alg_name = rule['alg']

            if rule.get('match') is None:
                input_ = FileReference(type=container_type, id=str(container['_id']), name=file_['name'])
                queue_job_legacy(alg_name, input_)
            else:
                inputs = { }

                for input_name, match_type in rule['match'].iteritems():
                    match = find_type_in_container(container, match_type)
                    if match is None:
                        raise Exception("No type " + match_type + " found for alg rule " + alg_name + " that should have been satisfied")
                    inputs[input_name] = FileReference(type=container_type, id=str(container['_id']), name=match['name'])

                gear = gears.get_gear_by_name(alg_name)
                job = Job(str(gear['_id']), inputs, tags=['auto', alg_name])
                job.insert()

            job_list.append(alg_name)

    return job_list

# TODO: consider moving to a module that has a variety of hierarchy-management helper functions
def get_rules_for_container(db, container):
    """
    Recursively walk the hierarchy until the project object is found.
    """

    if 'session' in container:
        session = db.sessions.find_one({'_id': container['session']})
        return get_rules_for_container(db, session)
    elif 'project' in container:
        project = db.projects.find_one({'_id': container['project']})
        return get_rules_for_container(db, project)
    else:
        # Assume container is a project, or a collection (which currently cannot have a rules property)
        result = list(db.project_rules.find({'project_id': str(container['_id'])}))

        if not result:
            print 'Container ' + str(container['_id']) + ' found NO rules'
            return []
        else:
            print 'Container ' + str(container['_id']) + ' found ' + str(len(result)) + ' rules'
            return result
