import os
import cgi
import json
import shutil
import hashlib

from . import config
from . import tempdir as tempfile
from . import util

DEFAULT_HASH_ALG='sha384'

def move_file(path, target_path):
    target_dir = os.path.dirname(target_path)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    shutil.move(path, target_path)


def move_form_file_field_into_storage(file_field):
    """
    Given a file form field, move the (downloaded, tempdir-stored) file into the final storage.

    Requires an augmented file field; see upload.process_upload() for details.
    """

    if not file_field.uuid or not file_field.path:
        raise Exception("Field is not a file field with uuid and path")

    base = config.get_item('persistent', 'data_path')
    move_file(file_field.path, os.path.join(base, 'v1', util.path_from_uuid(file_field.uuid)))


def hash_file_formatted(path, hash_alg=None, buffer_size=65536):
    """
    Return the scitran-formatted hash of a file, specified by path.
    """

    hash_alg = hash_alg or DEFAULT_HASH_ALG
    hasher = hashlib.new(hash_alg)

    with open(path, 'rb') as f:
        while True:
            data = f.read(buffer_size)
            if not data:
                break
            hasher.update(data)

    return util.format_hash(hash_alg, hasher.hexdigest())


class FileStoreException(Exception):
    pass


def process_form(request):
    """
    Some workarounds to make webapp2 process forms in an intelligent way.
    Normally webapp2/WebOb Reqest.POST would copy the entire request stream
    into a single file on disk.
    https://github.com/Pylons/webob/blob/cb9c0b4f51542a7d0ed5cc5bf0a73f528afbe03e/webob/request.py#L787
    https://github.com/moraes/webapp-improved/pull/12
    We pass request.body_file (wrapped wsgi input stream)
    to our custom subclass of cgi.FieldStorage to write each upload file
    to a separate file on disk, as it comes in off the network stream from the client.
    Then we can rename these files to their final destination,
    without copying the data gain.

    Returns (tuple):
        form: SingleFileFieldStorage instance
        tempdir: tempdir the file was stored in.

    Keep tempdir in scope until you don't need it anymore; it will be deleted on GC.
    """

    # Store form file fields in a tempdir
    tempdir = tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path'))

    # Copied from WebOb source:
    # https://github.com/Pylons/webob/blob/cb9c0b4f51542a7d0ed5cc5bf0a73f528afbe03e/webob/request.py#L790
    env = request.environ.copy()
    env.setdefault('CONTENT_LENGTH', '0')
    env['QUERY_STRING'] = ''

    field_storage_class = get_single_file_field_storage(
        tempdir.name
        )

    form = field_storage_class(
        fp=request.body_file, environ=env, keep_blank_values=True
    )

    return form, tempdir


def get_single_file_field_storage(upload_dir):
    # pylint: disable=attribute-defined-outside-init

    # We dynamically create this class because we
    # can't add arguments to __init__.
    # This is due to the FieldStorage we create
    # in turn creating a FieldStorage for different
    # parts of the form, with a hardcoded set of args
    # https://github.com/python/cpython/blob/1e3e162ff5c0cc656559c43914439ab3e5734f00/Lib/cgi.py#L696
    # https://github.com/python/cpython/blob/1e3e162ff5c0cc656559c43914439ab3e5734f00/Lib/cgi.py#L728

    class SingleFileFieldStorage(cgi.FieldStorage):
        bufsize = 2**20

        def make_file(self, binary=None):
            # Sanitize form's filename (read: prevent malicious escapes, bad characters, etc)
            self.filename = os.path.basename(self.filename)
            self.open_file = open(os.path.join(upload_dir, self.filename), 'wb')
            return self.open_file

        # override private method __write of superclass FieldStorage
        # _FieldStorage__file is the private variable __file of the same class
        def _FieldStorage__write(self, line):
            # pylint: disable=access-member-before-definition
            if self._FieldStorage__file is not None:
                # Always write fields of type "file" to disk for consistent renaming behavior
                if self.filename:
                    self.file = self.make_file('')

                    self.file.write(self._FieldStorage__file.getvalue())
                self._FieldStorage__file = None
            self.file.write(line)

    return SingleFileFieldStorage

# File extension --> scitran file type detection hueristics.
# Listed in precendence order.
with open(os.path.join(os.path.dirname(__file__), 'filetypes.json')) as fd:
    TYPE_MAP = json.load(fd)

KNOWN_FILETYPES = {ext: filetype for filetype, extensions in TYPE_MAP.iteritems() for ext in extensions}

def guess_type_from_filename(filename):
    particles = filename.split('.')[1:]
    extentions = ['.' + '.'.join(particles[i:]) for i in range(len(particles))]
    for ext in extentions:
        filetype = KNOWN_FILETYPES.get(ext.lower())
        if filetype:
            break
    else:
        filetype = None
    return filetype
