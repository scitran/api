import datetime
import elasticsearch

from .. import base
from .. import config

log = config.log


class SearchHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(SearchHandler, self).__init__(request, response)

    def get(self, cont_name=None, **kwargs):
        if self.public_request:
            self.abort(403, 'search is available only for authenticated users')
        size = self.get_param('size')
        body = self.request.json_body
        try:
            results = config.es.search(index='scitran', doc_type=cont_name, body=body, _source=['_id'], size=size or 10)
        except elasticsearch.exceptions.ConnectionError as e:
            self.abort(503, 'elasticsearch is not available')
        return results['hits']['hits']
