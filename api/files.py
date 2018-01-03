import cgi
import collections
import hashlib
import os
import re
import shutil

from . import util
from . import config
from . import tempdir as tempfile

DEFAULT_HASH_ALG='sha384'

def move_file(path, target_path):
    target_dir = os.path.dirname(target_path)
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    shutil.move(path, target_path)

def move_form_file_field_into_cas(file_field):
    """
    Given a file form field, move the (downloaded, tempdir-stored) file into the CAS.

    Requires an augmented file field; see upload.process_upload() for details.
    """

    if not file_field.hash or not file_field.path:
        raise Exception("Field is not a file field with hash and path")

    base   = config.get_item('persistent', 'data_path')
    cas    = util.path_from_hash(file_field.hash)
    move_file(file_field.path, os.path.join(base, cas))

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

class HashingFile(file):
    def __init__(self, file_path, hash_alg):
        super(HashingFile, self).__init__(file_path, "wb")
        self.hash_alg = hashlib.new(hash_alg)
        self.hash_name = hash_alg

    def write(self, data):
        self.hash_alg.update(data)
        return file.write(self, data)

    def get_hash(self):
        return self.hash_alg.hexdigest()

    def get_formatted_hash(self):
        return util.format_hash(self.hash_name, self.get_hash())

ParsedFile = collections.namedtuple('ParsedFile', ['info', 'path'])

def process_form(request, hash_alg=None):
    """
    Some workarounds to make webapp2 process forms in an intelligent way,
    and hash files we process.
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
        form: HashingFieldStorage instance
        tempdir: tempdir the file was stored in.

    Keep tempdir in scope until you don't need it anymore; it will be deleted on GC.
    """

    hash_alg = hash_alg or DEFAULT_HASH_ALG

    # Store form file fields in a tempdir
    tempdir = tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path'))

    # Copied from WebOb source:
    # https://github.com/Pylons/webob/blob/cb9c0b4f51542a7d0ed5cc5bf0a73f528afbe03e/webob/request.py#L790
    env = request.environ.copy()
    env.setdefault('CONTENT_LENGTH', '0')
    env['QUERY_STRING'] = ''

    field_storage_class = getHashingFieldStorage(
        tempdir.name, DEFAULT_HASH_ALG
        )

    form = field_storage_class(
        fp=request.body_file, environ=env, keep_blank_values=True
    )

    return (form, tempdir)

def getHashingFieldStorage(upload_dir, hash_alg):
    # pylint: disable=attribute-defined-outside-init

    # We dynamically create this class because we
    # can't add arguments to __init__.
    # This is due to the FieldStorage we create
    # in turn creating a FieldStorage for different
    # parts of the form, with a hardcoded set of args
    # https://github.com/python/cpython/blob/1e3e162ff5c0cc656559c43914439ab3e5734f00/Lib/cgi.py#L696
    # https://github.com/python/cpython/blob/1e3e162ff5c0cc656559c43914439ab3e5734f00/Lib/cgi.py#L728

    class HashingFieldStorage(cgi.FieldStorage):
        bufsize = 2**20

        def make_file(self, binary=None):
            # Sanitize form's filename (read: prevent malicious escapes, bad characters, etc)
            self.filename = os.path.basename(self.filename)
            # self.filename = util.sanitize_string_to_filename(self.filename)

            self.open_file = HashingFile(os.path.join(upload_dir, self.filename), hash_alg)
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

        def get_hash(self):
            return self.open_file.get_hash()

    return HashingFieldStorage

# File extension --> scitran file type detection hueristics.
# Listed in precendence order.

def guess_type_from_filename(filename):
    filetype = None
    m_length = 0
    cursor = config.db.filetypes.find({})

    for document in cursor:
        m = re.search(document['regex'], filename)
        if m and m_length < len(m.group(0)):
            filetype = document['_id']

    return filetype
