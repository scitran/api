
import pytest
from api.jobs import rules

# Statefully holds onto some construction args and can return tuples to unroll for calling rules.eval_match.
# Might indicate a need for a match tuple in rules.py.
class rulePart:
    # Hold onto some param state
    def __init__(self, match_type=None, match_param=None, file_=None, container=None):
        self.match_type  = match_type
        self.match_param = match_param
        self.file_       = file_
        self.container   = container

    # Return params as tuple, optionally with some modifications
    def gen(self, match_type=None, match_param=None, file_=None, container=None):

        return (
            match_type  if match_type  else self.match_type,
            match_param if match_param else self.match_param,
            file_       if file_       else self.file_,
            container   if container   else self.container,
        )

# DISCUSS: this basically asserts that the log helper doesn't throw, which is of non-zero but questionable value.
# Could instead be marked for pytest et. al to ignore coverage? Desirability? Compatibility?
def test_log_file_key_error():
    rules._log_file_key_error({'name': 'wat'}, {'_id': 0}, 'example')


def test_eval_match_file_type():
    part = rulePart(match_type='file.type', match_param='dicom')

    args = part.gen(file_={'type': 'dicom' })
    result = rules.eval_match(*args)
    assert result == True

    args = part.gen(file_={'type': 'nifti' })
    result = rules.eval_match(*args)
    assert result == False

    # Check match returns false without raising when not given a file.type
    args = part.gen(file_={'a': 'b'}, container={'a': 'b'})
    result = rules.eval_match(*args)
    assert result == False

def test_eval_match_file_name_match_exact():
    part = rulePart(match_type='file.name', match_param='file.txt')

    args = part.gen(file_={'name': 'file.txt' })
    result = rules.eval_match(*args)
    assert result == True

    args = part.gen(file_={'name': 'file2.txt' })
    result = rules.eval_match(*args)
    assert result == False

def test_eval_match_file_name_match_relative():
    part = rulePart(match_type='file.name', match_param='*.txt')

    args = part.gen(file_={'name': 'file.txt' })
    result = rules.eval_match(*args)
    assert result == True

    args = part.gen(file_={'name': 'file.log' })
    result = rules.eval_match(*args)
    assert result == False

def test_eval_match_file_measurements():
    part = rulePart(match_type='file.measurements', file_={'measurements': ['a', 'diffusion', 'b'] })

    args = part.gen(match_param='diffusion')
    result = rules.eval_match(*args)
    assert result == True

    args = part.gen(match_param='c')
    result = rules.eval_match(*args)
    assert result == False

    # Check match returns false without raising when not given a file.type
    args = part.gen(file_={'a': 'b'}, container={'a': 'b'})
    result = rules.eval_match(*args)
    assert result == False

def test_eval_match_container_measurement():
    part = rulePart(match_type='container.measurement', container={'measurement': 'diffusion'})

    args = part.gen(match_param='diffusion')
    result = rules.eval_match(*args)
    assert result == True

    args = part.gen(match_param='c')
    result = rules.eval_match(*args)
    assert result == False

def test_eval_match_container_has_type():
    part = rulePart(match_type='container.has-type', container={'files': [
            {'measurements': ['a', 'diffusion', 'b']},
            {'measurements': ['c', 'other', 'b']},
        ]})

    args = part.gen(match_param='other')
    result = rules.eval_match(*args)
    assert result == True

    args = part.gen(match_param='d')
    result = rules.eval_match(*args)
    assert result == False

def test_eval_match_unknown_type():
    with pytest.raises(Exception):
        rules.eval_match('does-not-exist', None, None, None)


def test_eval_rule_any():
    container = {'a': 'b'}

    rule = {
        "any": [
            ["file.type",             "dicom"     ],
            ["file.name",             "*.dcm"     ],
        ],
        "all": [],
        "alg": "dcm2nii",
    }

    file_ = {'name': 'hello.dcm', 'type': 'a'}
    result = rules.eval_rule(rule, file_, container)
    assert result == True

    file_ = {'name': 'hello.txt', 'type': 'dicom'}
    result = rules.eval_rule(rule, file_, container)
    assert result == True

    file_ = {'name': 'hello.dcm', 'type': 'dicom'}
    result = rules.eval_rule(rule, file_, container)
    assert result == True

    file_ = {'name': 'hello.txt', 'type': 'a'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False

def test_eval_rule_all():
    container = {'a': 'b'}

    rule = {
        "any": [
        ],
        "all": [
            ["file.type",             "dicom"     ],
            ["file.name",             "*.dcm"     ],
        ],
        "alg": "dcm2nii",
    }

    file_ = {'name': 'hello.dcm', 'type': 'a'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False

    file_ = {'name': 'hello.txt', 'type': 'dicom'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False

    file_ = {'name': 'hello.dcm', 'type': 'dicom'}
    result = rules.eval_rule(rule, file_, container)
    assert result == True

    file_ = {'name': 'hello.txt', 'type': 'a'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False

def test_eval_rule_any_all():
    container = {'a': 'b'}

    rule = {
        "any": [
            ["file.type",             "dicom"     ],
            ["file.name",             "*.dcm"     ],
        ],
        "all": [
            ["file.type",             "dicom"     ],
            ["file.name",             "*.dcm"     ],
        ],
        "alg": "dcm2nii",
    }

    file_ = {'name': 'hello.dcm', 'type': 'a'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False

    file_ = {'name': 'hello.txt', 'type': 'dicom'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False

    file_ = {'name': 'hello.dcm', 'type': 'dicom'}
    result = rules.eval_rule(rule, file_, container)
    assert result == True

    file_ = {'name': 'hello.txt', 'type': 'a'}
    result = rules.eval_rule(rule, file_, container)
    assert result == False
