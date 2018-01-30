import atexit
import json
import os
import traceback
import webapp2

# Enable code coverage for testing when API is started
# Start coverage before local module loading so their def and imports are counted
#   http://coverage.readthedocs.io/en/coverage-4.2/faq.html
if os.environ.get("SCITRAN_RUNTIME_COVERAGE") == "true": # pragma: no cover - oh, the irony
    def save_coverage(cov):
        print("Saving coverage")
        cov.stop()
        cov.save()

    def start_coverage():
        import coverage
        print("Enabling code coverage")
        cov = coverage.coverage(source=["api"], data_file="/tmp/.coverage.integration-tests")
        cov.start()
        atexit.register(save_coverage, cov)

    start_coverage()


from ..api import endpoints
from .. import config
from . import encoder
from .. import util
from .request import SciTranRequest

try:
    import uwsgi
except ImportError:
    uwsgi = None

log = config.log

def dispatcher(router, request, response):
    try:
        if uwsgi is not None:
            uwsgi.set_logvar('request_id', request.id)
    except: # pylint: disable=bare-except
        request.logger.error("Error setting request_id log var", exc_info=True)

    try:
        rv = router.default_dispatcher(request, response)
        if rv is not None:
            response.write(json.dumps(rv, default=encoder.custom_json_serializer))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
    except webapp2.HTTPException as e:
        util.send_json_http_exception(response, str(e), e.code, request.id)
    except Exception as e: # pylint: disable=broad-except
        request.logger.error("Error dispatching request", exc_info=True)
        if config.get_item('core', 'debug'):
            message = traceback.format_exc()
        else:
            message = 'Internal Server Error'
        util.send_json_http_exception(response, message, 500, request.id)

def app_factory(*_, **__):
    # pylint: disable=protected-access,unused-argument

    # don't use config.get_item() as we don't want to require the database at startup
    application = webapp2.WSGIApplication(endpoints, debug=config.__config['core']['debug'])
    application.router.set_dispatcher(dispatcher)
    application.request_class = SciTranRequest
    return application
