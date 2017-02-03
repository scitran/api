import os
import pytz
import uuid
import datetime
import mimetypes
import bson.objectid
import tempdir as tempfile
import enum as baseEnum

MIMETYPES = [
    ('.bvec', 'text', 'bvec'),
    ('.bval', 'text', 'bval'),
    ('.m', 'text', 'matlab'),
    ('.sh', 'text', 'shell'),
    ('.r', 'text', 'r'),
]
for mt in MIMETYPES:
    mimetypes.types_map.update({mt[0]: mt[1] + '/' + mt[2]})


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


def user_perm(permissions, _id, site=None):
    for perm in permissions:
        if perm['_id'] == _id and perm.get('site') == site:
            return perm
    else:
        return {}


def container_fileinfo(container, filename):
    for fileinfo in container.get('files', []):
        if fileinfo['filename'] == filename:
            return fileinfo
    else:
        return None


def download_ticket(ip, type_, target, filename, size, projects = None):
    return {
        '_id': str(uuid.uuid4()),
        'timestamp': datetime.datetime.utcnow(),
        'ip': ip,
        'type': type_,
        'target': target,
        'filename': filename,
        'size': size,
        'projects': projects or []
    }


def guess_mimetype(filepath):
    """Guess MIME type based on filename."""
    mime, _ = mimetypes.guess_type(filepath)
    return mime or 'application/octet-stream'


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


def custom_json_serializer(obj):
    if isinstance(obj, bson.objectid.ObjectId):
        return str(obj)
    elif isinstance(obj, datetime.datetime):
        return pytz.timezone('UTC').localize(obj).isoformat()
    raise TypeError(repr(obj) + " is not JSON serializable")

class Enum(baseEnum.Enum):
    # Enum strings are prefixed by their class: "Category.classifier".
    # This overrides that behaviour and removes the prefix.
    def __str__(self):
        return str(self.name)

class ObjectId(bson.objectid.ObjectId):

    def __init__(self, s=None):
        if s is None:
            super(ObjectId, self).__init__()
            return
        if 6 <= len(s) < 12:
            s = ' ' * (12 - len(s)) + s
        super(ObjectId, self).__init__(s)

    @staticmethod
    def is_valid(s):
        if 6 <= len(s) < 12:
            s = ' ' * (12 - len(s)) + s
        return bson.objectid.ObjectId.is_valid(s)
