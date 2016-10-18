import fnmatch

from .. import config
from ..dao.containerutil import FileReference

from . import gear_helpers
from .jobs import Job

log = config.log


#
# {
#   At least one match from this array must succeed, or array must be empty
#   "any": [
#       ["file.type",             "dicom"     ] # Match the file's type
#       ["file.name",             "*.dcm"     ] # Match a shell glob for the file name
#       ["file.measurements",     "diffusion" ] # Match any of the file's measurements
#       ["container.has-type",    "bvec"      ] # Match the container having any file (including this one) with this type
#   ]
#
#   All matches from array must succeed, or array must be empty
#   "all": [
#   ]
#
#   Algorithm to run if both sets of rules match
#   "alg": "dcm2nii"
# }
#

MATCH_TYPES = [
    'file.type',
    'file.name',
    'file.measurements',
    'container.has-type'
]

def get_base_rules():
    """
    Fetch the install-global gear rules from the database
    """
    rule_doc = config.db.singletons.find_one({'_id': 'rules'}) or {}
    return rule_doc.get('rule_list', [])

def _log_file_key_error(file_, container, error):
    log.warning('file ' + file_.get('name', '?') + ' in container ' + str(container.get('_id', '?')) + ' ' + error)

def eval_match(match_type, match_param, file_, container):
    """
    Given a match entry, return if the match succeeded.
    """

    # Match the file's type
    if match_type == 'file.type':
        try:
            return file_['type'] == match_param
        except KeyError:
            _log_file_key_error(file_, container, 'has no type key')
            return False

    # Match a shell glob for the file name
    elif match_type == 'file.name':
        return fnmatch.fnmatch(file_['name'], match_param)

    # Match any of the file's measurements
    elif match_type == 'file.measurements':
        try:
            return match_param in file_['measurements']
        except KeyError:
            _log_file_key_error(file_, container, 'has no measurements key')
            return False

    # Match the container having any file (including this one) with this type
    elif match_type == 'container.has-type':
        for c_file in container['files']:
            if match_param == c_file.get('type'):
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
        if eval_match(match[0], match[1], file_, container):
            has_match = True
            break

    # If there were matches in the 'any' array and none of them succeeded
    if must_match and not has_match:
        return False

    # Are there matches in the 'all' set?
    for match in rule.get('all', []):
        if not eval_match(match[0], match[1], file_, container):
            return False

    return True

def queue_job_legacy(algorithm_id, input_):
    """
    Tie together logic used from the no-manifest, single-file era.
    Takes a single FileReference instead of a map.
    """

    gear = gear_helpers.get_gear_by_name(algorithm_id)

    if len(gear['gear']['inputs']) != 1:
        raise Exception("Legacy gear enqueue attempt of " + algorithm_id + " failed: must have exactly 1 input in manifest")

    input_name = gear['gear']['inputs'].keys()[0]

    inputs = {
        input_name: input_
    }

    job = Job(algorithm_id, inputs)
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

                job = Job(alg_name, inputs)
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
        return container.get('rules', [])
