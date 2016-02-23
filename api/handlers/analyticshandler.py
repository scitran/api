import datetime

from .. import base
from .. import util
from .. import config
from ..auth import containerauth, always_ok
from ..dao import APIStorageException, analytics

log = config.log


class AnalyticsHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(AnalyticsHandler, self).__init__(request, response)

    def get(self, cont_name, **kwargs):
        start_date = self.get_param('start_date')
        if start_date:
            year, month, day = [int(i) for i in start_date.split('-')]
            start_date = datetime.datetime(year, month, day)
        end_date = self.get_param('end_date')
        if end_date:
            year, month, day = [int(i) for i in end_date.split('-')]
            end_date = datetime.datetime(year, month, day + 1)
        if self.superuser_request:
            user_id = self.get_param('user_id')
            user_site = self.get_param('user_site') or config.get_item('site', 'id')
        elif not self.get_param('user_id'):
            user_id = self.uid
            user_site = self.user_site
        elif self.get_param('user_id') != self.uid or self.get_param('site') != self.user_site:
            self.abort(400, 'user must be admin to perform the request')
        limit = 10 if self.get_param('limit') is None else int(self.get_param('limit'))
        result = analytics.get(
            self.get_param('type'),
            user_id, user_site,
            start_date,
            end_date,
            self.get_param('count'),
            limit
        )
        return result

    def post(self, cont_name, **kwargs):
        analytic_type = self.get_param('type')
        if not analytic_type:
            self.abort(400, 'missing view type in request')
        result = analytics.add(
            analytic_type,
            self.uid,
            self.user_site,
            datetime.datetime.utcnow()
        )
        return result
