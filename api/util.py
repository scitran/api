import datetime
import enum as baseEnum
import errno
import hashlib
import json
import mimetypes
import os
import random
import re
import requests
import string
import uuid

MIMETYPES = [
    ('.bvec', 'text', 'bvec'),
    ('.bval', 'text', 'bval'),
    ('.m', 'text', 'matlab'),
    ('.sh', 'text', 'shell'),
    ('.r', 'text', 'r'),
]
for mt in MIMETYPES:
    mimetypes.types_map.update({mt[0]: mt[1] + '/' + mt[2]})

# NOTE unused function
def hrsize(size):
    if size < 1000:
        return '%d%s' % (size, 'B')
    for suffix in 'KMGTPEZY':
        size /= 1024.
        if size < 10.:
            return '%.1f%sB' % (size, suffix)
        if size < 1000.:
            return '%.0f%sB' % (size, suffix)
    return '%.0f%sB' % (size, 'Y')

def mongo_sanitize(field):
    return field.replace('.', '_')

def mongo_dict(d):
    def _mongo_list(d, pk=''):
        pk = pk and pk + '.'
        return sum(
            [
            _mongo_list(v, pk+mongo_sanitize(k)) if isinstance(v, dict) else [(pk+mongo_sanitize(k), v)]
            for k, v in d.iteritems()
            ], []
        )
    return dict(_mongo_list(d))

def mongo_sanitize_fields(d):
    """
    Sanitize keys of arbitrarily structured map without flattening into dot notation

    Adapted from http://stackoverflow.com/questions/8429318/how-to-use-dot-in-field-name
    """

    if isinstance(d, dict):
        return {mongo_sanitize_fields(str(key)): value if isinstance(value, str) else mongo_sanitize_fields(value) for key,value in d.iteritems()}
    elif isinstance(d, list):
        return [mongo_sanitize_fields(element) for element in d]
    elif isinstance(d, str):
        # not allowing dots nor dollar signs in fieldnames
        d = d.replace('.', '_')
        d = d.replace('$', '-')
        return d
    else:
        return d

def deep_update(d, u):
    """
    Makes a deep update of dict d with dict u
    Adapted from http://stackoverflow.com/a/3233356
    """
    for k, v in u.iteritems():
        if isinstance(v, dict):
            r = deep_update(d.get(k, {}), v)
            d[k] = r
        else:
            d[k] = u[k]
    return d


def user_perm(permissions, _id, site=None):
    for perm in permissions:
        if perm['_id'] == _id and perm.get('site') == site:
            return perm
    return {}

def is_user_id(uid):
    """
    Checks to make sure uid matches uid regex
    """
    pattern = re.compile('^[0-9a-zA-Z.@_-]*$')
    return bool(pattern.match(uid))


# NOTE unused function
def is_group_id(gid):
    """
    Checks to make sure uid matches uid regex
    """
    pattern = re.compile('^[0-9a-z][0-9a-z.@_-]{0,30}[0-9a-z]$')
    return bool(pattern.match(gid))

def resolve_gravatar(email):
    """
    Given an email, returns a URL if that email has a gravatar set.
    Otherwise returns None.
    """

    gravatar = 'https://gravatar.com/avatar/' + hashlib.md5(email).hexdigest() + '?s=512'
    if requests.head(gravatar, params={'d': '404'}):
        return gravatar
    else:
        return None


# NOTE unused function
def container_fileinfo(container, filename): # pragma: no cover
    for fileinfo in container.get('files', []):
        if fileinfo['filename'] == filename:
            return fileinfo
    return None


def download_ticket(ip, type_, target, filename, size, projects = None, origin=None):
    return {
        '_id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.utcnow(),
        'ip': ip,
        'type': type_,
        'target': target,
        'filename': filename,
        'size': size,
        'projects': projects or [],
        'origin': origin
    }


def guess_mimetype(filepath):
    """Guess MIME type based on filename."""
    mime, _ = mimetypes.guess_type(filepath)
    return mime or 'application/octet-stream'

def sanitize_string_to_filename(value):
    """
    Best-effort attempt to remove blatantly poor characters from a string before turning into a filename.

    Happily stolen from the internet, then modified.
    http://stackoverflow.com/a/7406369
    """

    keepcharacters = (' ', '.', '_', '-')
    return "".join([c for c in value if c.isalnum() or c in keepcharacters]).rstrip()

def obj_from_map(_map):
    """
    Creates an anonymous object with properties determined by the passed (shallow) map.
    Hides the esoteric python syntax.
    """

    return type('',(object,),_map)()

def path_from_hash(hash_):
    """
    create a filepath from a hash
    e.g.
    hash_ = v0-sha384-01b395a1cbc0f218
    will return
    v0/sha384/01/b3/v0-sha384-01b395a1cbc0f218
    """
    hash_version, hash_alg, actual_hash = hash_.split('-')
    first_stanza = actual_hash[0:2]
    second_stanza = actual_hash[2:4]
    path = (hash_version, hash_alg, first_stanza, second_stanza, hash_)
    return os.path.join(*path)


def format_hash(hash_alg, hash_):
    """
    format the hash including version and algorithm
    """
    return '-'.join(('v0', hash_alg, hash_))


def send_json_http_exception(response, message, code, custom=None):
    response.set_status(code)
    content = {
        'message': message,
        'status_code': code
    }
    if custom:
        content.update(custom)

    json_content = json.dumps(content)
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.write(json_content)


class Enum(baseEnum.Enum):
    # Enum strings are prefixed by their class: "Category.classifier".
    # This overrides that behaviour and removes the prefix.
    def __str__(self):
        return str(self.name)

    # Allow equality comparison with strings against the enum's name.

    def __ne__(self, other):
        if isinstance(other, basestring):
            return self.name != other
        else:
            return super.__ne__(other)

    def __eq__(self, other):
        if isinstance(other, basestring):
            return self.name == other
        else:
            return super.__eq__(other)

def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise

NONCE_CHARS  = string.ascii_letters + string.digits
NONCE_LENGTH = 18

def create_nonce():
    x = len(NONCE_CHARS)

    # Class that uses the os.urandom() function for generating random numbers.
    # https://docs.python.org/2/library/random.html#random.SystemRandom
    randrange = random.SystemRandom().randrange

    return ''.join([NONCE_CHARS[randrange(x)] for _ in range(NONCE_LENGTH)])
