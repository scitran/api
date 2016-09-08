import unittest

import mock
from testfixtures import LogCapture

import api.request

class TestRequest(unittest.TestCase):
    def setUp(self):
        self.log_capture = LogCapture()
        self.request = api.request.SciTranRequest({})
        api.request.set_current_request(self.request)

    def tearDown(self):
        api.request.set_current_request(None)
        LogCapture.uninstall_all()

    def test_request_logger_adapter(self):
        request = api.request.get_current_request()
        self.assertTrue(self.request is request)
        self.assertEqual(len(request.id), 19)
        test_log_message = "test log message"
        request.logger.error(test_log_message)
        expected_log_output = "{0} request_id={1}".format(
            test_log_message, request.id
        )
        self.log_capture.check(('scitran.api', 'ERROR', expected_log_output))

    def test_setting_request_error(self):
        with self.assertRaises(ValueError):
            api.request.set_current_request(mock.MagicMock())
