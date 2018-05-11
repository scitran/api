
class APIAuthProviderException(Exception):
    pass

# Creating mulitple containers with same id
class APIConflictException(Exception):
    pass

# For checking database consistency
class APIConsistencyException(Exception):
    pass

# API could not find what was requested
class APINotFoundException(Exception):
    pass

class APIPermissionException(Exception):
    def __init__(self, msg, errors=None):

        super(APIPermissionException, self).__init__(msg)
        self.errors = errors

class APIRefreshTokenException(Exception):
    # Specifically alert a client when the user's refresh token expires
    # Requires client to ask for `offline=true` permission to receive a new one
    def __init__(self, msg):

        super(APIRefreshTokenException, self).__init__(msg)
        self.errors = {'core_status_code': 'invalid_refresh_token'}

class APIReportException(Exception):
    pass

# Invalid or missing parameters for a report request
class APIReportParamsException(Exception):
    pass

class APIStorageException(Exception):
    pass

# User Id not found or disabled
class APIUnknownUserException(Exception):
    pass

class APIValidationException(Exception):
    def __init__(self, errors):

        super(APIValidationException, self).__init__('Validation Error.')
        self.errors = errors

# Payload for a POST or PUT does not match mongo json schema
class DBValidationException(Exception):
    pass

class FileStoreException(Exception):
    pass

# File Form for upload requests made by client is incorrect
class FileFormException(Exception):
    pass

# Payload for a POST or PUT does not match input json schema
class InputValidationException(Exception):
    pass
