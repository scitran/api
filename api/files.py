import os
import cgi
import json
import shutil
import hashlib
import datetime
import collections

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

def hash_file_formatted(path, hash_alg=None):
    """
    Return the scitran-formatted hash of a file, specified by path.

    REVIEW: if there's an intelligent io-copy in python stdlib, I missed it. This uses an arbitrary buffer size :/
    """

    hash_alg = hash_alg or DEFAULT_HASH_ALG
    hasher = hashlib.new(hash_alg)

    BUF_SIZE = 65536

    with open(path, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            hasher.update(data)

    return util.format_hash(hash_alg, hasher.hexdigest())


class FileStoreException(Exception):
    pass

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
    Some workarounds to make webapp2 process forms in an intelligent way, and hash files we process.
    Could subsume getHashingFieldStorage.

    This is a bit arcane, and deals with webapp2 / uwsgi / python complexities. Ask a team member, sorry!

    Returns the processed form, and the tempdir it was stored in.
    Keep tempdir in scope until you don't need it anymore; it will be deleted on GC.
    """

    hash_alg = hash_alg or DEFAULT_HASH_ALG

    # Store form file fields in a tempdir
    tempdir = tempfile.TemporaryDirectory(prefix='.tmp', dir=config.get_item('persistent', 'data_path'))

    # Deep vodoo; docs?
    env = request.environ.copy()
    env.setdefault('CONTENT_LENGTH', '0')
    env['QUERY_STRING'] = ''

    # Wall-clock warning: despite its name, getHashingFieldStorage will actually process the entire form to disk. This involves recieving the entire upload stream and storing any files in the tempdir.
    form = getHashingFieldStorage(tempdir.name, DEFAULT_HASH_ALG)(
        fp=request.body_file, environ=env, keep_blank_values=True
    )

    return (form, tempdir)

def getHashingFieldStorage(upload_dir, hash_alg):
    # pylint: disable=attribute-defined-outside-init

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
                # use the make_file method only if the form includes a filename
                # e.g. do not create a file and a hash for the form metadata.
                if self.filename:
                    self.file = self.make_file('')

                    self.file.write(self._FieldStorage__file.getvalue())
                self._FieldStorage__file = None
            self.file.write(line)

        def get_hash(self):
            return self.open_file.get_hash()

    return HashingFieldStorage


class FileStore(object):
    """This class provides and interface for file uploads.
    To perform an upload the client of the class should follow these steps:

    1) initialize the request
    2) save a temporary file
    3) check identical
    4) move the temporary file to its destination

    The operations could be safely interleaved with other actions like permission checks or database updates.
    """

    def __init__(self, request, dest_path, filename=None, hash_alg=DEFAULT_HASH_ALG):
        self.body = request.body_file
        self.environ = request.environ.copy()
        self.environ.setdefault('CONTENT_LENGTH', '0')
        self.environ['QUERY_STRING'] = ''
        self.hash_alg = hash_alg
        start_time = datetime.datetime.utcnow()
        if request.content_type == 'multipart/form-data':
            self._save_multipart_file(dest_path, hash_alg)
            self.payload = request.POST.mixed()
        else:
            self.payload = request.POST.mixed()
            self.filename = filename or self.payload.get('filename')
            self._save_body_file(dest_path, filename, hash_alg)
        self.mimetype = util.guess_mimetype(self.filename)
        self.path = os.path.join(dest_path, self.filename)
        self.duration = datetime.datetime.utcnow() - start_time
        # the hash format is:
        # <version>-<hashing algorithm>-<actual hash>
        # version will track changes on hash related methods like for example how we check for identical files.
        self.hash = util.format_hash(hash_alg, self.received_file.get_hash())
        self.size = os.path.getsize(self.path)

    def _save_multipart_file(self, dest_path, hash_alg):
        form = getHashingFieldStorage(dest_path, hash_alg)(fp=self.body, environ=self.environ, keep_blank_values=True)

        self.received_file = form['file'].file
        self.filename = os.path.basename(form['file'].filename)
        self.tags = json.loads(form['tags'].file.getvalue()) if 'tags' in form else None
        self.metadata = json.loads(form['metadata'].file.getvalue()) if 'metadata' in form else None

    def _save_body_file(self, dest_path, filename, hash_alg):
        if not filename:
            raise FileStoreException('filename is required for body uploads')
        self.filename = os.path.basename(filename)
        self.received_file = HashingFile(os.path.join(dest_path, filename), hash_alg)
        for chunk in iter(lambda: self.body.read(2**20), ''):
            self.received_file.write(chunk)
        self.tags = None
        self.metadata = None

    def move_file(self, target_path):
        move_file(self.path, target_path)
        self.path = target_path

# TODO: Hopefully deprecated by unification branch
class MultiFileStore(object):
    """This class provides and interface for file uploads.
    """

    def __init__(self, request, dest_path, hash_alg=DEFAULT_HASH_ALG):
        self.body = request.body_file
        self.environ = request.environ.copy()
        self.environ.setdefault('CONTENT_LENGTH', '0')
        self.environ['QUERY_STRING'] = ''
        self.hash_alg = hash_alg
        self.files = {}
        self._save_multipart_files(dest_path, hash_alg)
        self.payload = request.POST.mixed()

    def _save_multipart_files(self, dest_path, hash_alg):
        form = getHashingFieldStorage(dest_path, hash_alg)(fp=self.body, environ=self.environ, keep_blank_values=True)
        self.metadata = json.loads(form['metadata'].file.getvalue()) if 'metadata' in form else None
        for field in form:
            if form[field].filename:
                filename = os.path.basename(form[field].filename)
                self.files[filename] = ParsedFile(
                    {
                        'hash': util.format_hash(hash_alg, form[field].file.get_hash()),
                        'size': os.path.getsize(os.path.join(dest_path, filename)),
                        'mimetype': util.guess_mimetype(filename)
                    }, os.path.join(dest_path, filename))


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
