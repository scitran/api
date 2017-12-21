import logging
import time
import uuid
from webob.request import Request

from .. import config
from .. import util

AccessType = util.Enum('AccessType', {
    'view_container':   'view_container',
    'view_subject':     'view_subject',
    'view_file':        'view_file',
    'download_file':    'download_file',
    'delete_file':      'delete_file',
    'delete_analysis':  'delete_analysis',
    'user_login':       'user_login',
    'user_logout':      'user_logout'
})
AccessTypeList = [type_name for type_name, member in AccessType.__members__.items()]


class SciTranRequest(Request):
    """Extends webob.request.Request"""
    def __init__(self, *args, **kwargs):
        super(SciTranRequest, self).__init__(*args, **kwargs)
        self.id = "{random_chars}-{timestamp}".format(
            timestamp = str(int(time.time())),
            random_chars = str(uuid.uuid4().hex)[:8]
            )
        self.logger =  get_request_logger(self.id)

class RequestLoggerAdapter(logging.LoggerAdapter):
    """A LoggerAdapter to add request_id context"""
    def process(self, msg, kwargs):
        context_message =  "{0} request_id={1}".format(
            msg, self.extra['request_id']
            )
        return context_message, kwargs

def get_request_logger(request_id):
    """Given a request_id, produce a Logger or LoggerAdapter"""
    extra = {"request_id":request_id}
    logger = RequestLoggerAdapter(config.log, extra=extra)
    return logger


def log_access(access_type, cont_kwarg='cont_name', cont_id_kwarg='cid'):
    """
    A decorator to log a user or drone's access to an endpoint
    """
    def log_access_decorator(handler_method):
        def log_user_access_from_request(self, *args, **kwargs):
            result = handler_method(self, *args, **kwargs)

            cont_name = None
            cont_id = None

            if access_type not in [AccessType.user_login, AccessType.user_logout]:

                cont_name = kwargs.get(cont_kwarg)
                cont_id = kwargs.get(cont_id_kwarg)

                # Only log view_container events when the container is a session
                if access_type is AccessType.view_container and not self.phi:
                    return result

            self.log_user_access(access_type, cont_name, cont_id)

            return result
        return log_user_access_from_request
    return log_access_decorator
