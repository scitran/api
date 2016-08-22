import logging
import threading
import time
import uuid

from webob.request import Request

from . import config

# Make a thread-local variable to store the current request
threadLocal = threading.local()
threadLocal.current_request = None

def set_current_request(request):
    if threadLocal.current_request is not None and request is not None:
        raise ValueError("Attempted to overwrite current request")
    threadLocal.current_request = request

def get_current_request():
    return threadLocal.current_request

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
