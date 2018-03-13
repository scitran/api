import os
import cgi
import json
import six
import hashlib
import uuid

import fs.move
import fs.subfs
import fs.path
import fs.errors

from . import config, util

DEFAULT_HASH_ALG = 'sha384'

class FileProcessor(object):
    def __init__(self, base, presistent_fs, tempdir_name=None):
        self.base = base
        if not tempdir_name:
            self._tempdir_name = str(uuid.uuid4())
        else:
            self._tempdir_name = tempdir_name
        self._presistent_fs = presistent_fs
        self._presistent_fs.makedirs(fs.path.join('tmp', self._tempdir_name), recreate=True)
        self._temp_fs = fs.subfs.SubFS(presistent_fs, fs.path.join('tmp', self._tempdir_name))

    def store_temp_file(self, src_path, dest_path):
        if not isinstance(src_path, unicode):
            src_path = six.u(src_path)
        if not isinstance(dest_path, unicode):
            dest_path = six.u(dest_path)
        dst_dir = fs.path.dirname(dest_path)
        self._presistent_fs.makedirs(dst_dir, recreate=True)
        self._presistent_fs.move(src_path=fs.path.join('tmp', self._tempdir_name, src_path), dst_path=dest_path)

    def process_form(self, request):
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

        # Copied from WebOb source:
        # https://github.com/Pylons/webob/blob/cb9c0b4f51542a7d0ed5cc5bf0a73f528afbe03e/webob/request.py#L790
        env = request.environ.copy()
        env.setdefault('CONTENT_LENGTH', '0')
        env['QUERY_STRING'] = ''

        field_storage_class = get_single_file_field_storage(self._temp_fs)

        form = field_storage_class(
            fp=request.body_file, environ=env, keep_blank_values=True
        )

        return form

    def hash_file_formatted(self, filepath, f_system, hash_alg=None, buffer_size=65536):
        """
        Return the scitran-formatted hash of a file, specified by path.
        """

        if not isinstance(filepath, unicode):
            filepath = six.u(filepath)

        hash_alg = hash_alg or DEFAULT_HASH_ALG
        hasher = hashlib.new(hash_alg)

        with f_system.open(filepath, 'rb') as f:
            while True:
                data = f.read(buffer_size)
                if not data:
                    break
                hasher.update(data)

        return util.format_hash(hash_alg, hasher.hexdigest())

    @property
    def temp_fs(self):
        return self._temp_fs

    @property
    def persistent_fs(self):
        return self._presistent_fs

    def __exit__(self, exc, value, tb):
        self.close()

    def __del__(self):
        self.close()

    def close(self):
        # Cleaning up
        self._presistent_fs.listdir(fs.path.join('tmp', self._tempdir_name))
        self._presistent_fs.removetree(fs.path.join('tmp', self._tempdir_name))


def get_single_file_field_storage(file_system):
    # pylint: disable=attribute-defined-outside-init

    # We dynamically create this class because we
    # can't add arguments to __init__.
    # This is due to the FieldStorage we create
    # in turn creating a FieldStorage for different
    # parts of the form, with a hardcoded set of args
    # https://github.com/python/cpython/blob/1e3e162ff5c0cc656559c43914439ab3e5734f00/Lib/cgi.py#L696
    # https://github.com/python/cpython/blob/1e3e162ff5c0cc656559c43914439ab3e5734f00/Lib/cgi.py#L728

    class SingleFileFieldStorage(cgi.FieldStorage):
        bufsize = 2 ** 20

        def make_file(self, binary=None):
            # Sanitize form's filename (read: prevent malicious escapes, bad characters, etc)

            self.filename = fs.path.basename(self.filename)
            self.hasher = hashlib.new(DEFAULT_HASH_ALG)
            if not isinstance(self.filename, unicode):
                self.filename = six.u(self.filename)
            self.open_file = file_system.open(self.filename, 'wb')
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
                    self.hasher.update(self._FieldStorage__file.getvalue())
                self._FieldStorage__file = None

            self.file.write(line)

            # NOTE: In case of metadata, we don't have a file name and we also don't have a hasher,
            # so skipping the hasher.update
            if self.filename:
                self.hasher.update(line)

    return SingleFileFieldStorage

class FileStoreException(Exception):
    pass

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


def get_valid_file(file_info):
    file_id = file_info.get('_id', '')
    file_hash = file_info.get('hash', '')
    file_uuid_path = None
    file_hash_path = None

    if file_hash:
        file_hash_path = util.path_from_hash(file_hash)

    if file_id:
        file_uuid_path = util.path_from_uuid(file_id)

    if config.support_legacy_fs:
        if file_hash_path and config.legacy_fs.isfile(file_hash_path):
            return file_hash_path, config.legacy_fs
        elif file_uuid_path and config.legacy_fs.isfile(file_uuid_path):
            return file_uuid_path, config.legacy_fs

    if file_uuid_path and config.fs.isfile(file_uuid_path):
        return file_uuid_path, config.fs
    else:
        raise fs.errors.ResourceNotFound('File not found: %s', file_info['name'])


def get_signed_url(file_path, file_system, filename=None, purpose='download'):
    try:
        if hasattr(file_system, 'get_signed_url'):
            return file_system.get_signed_url(file_path, filename=filename, purpose=purpose)
    except fs.errors.NoURL:
        return None


def get_fs_by_file_path(file_path):
    if config.support_legacy_fs and config.legacy_fs.isfile(file_path):
        return config.legacy_fs

    if config.fs.isfile(file_path):
        return config.fs
    else:
        raise fs.errors.ResourceNotFound('File not found: %s', file_path)
