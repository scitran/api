import copy
import json

from elasticsearch import ElasticsearchException, TransportError, RequestError, helpers

from ..web import base
from .. import config
from ..auth import require_login, require_superuser

log = config.log

"""
EXAMPLE_SESSION_QUERY = {
  "size": 0,
  "query": {
    "match": {
      "_all": "test'"
    }
  },
  "aggs": {
    "by_session": {
      "terms": {
        "field": "session._id",
        "size": 100
      },
      "aggs": {
        "by_top_hit": {
          "top_hits": {
            "size": 1
          }
        }
      }
    }
  }
}

EXAMPLE_ACQUISITION_QUERY = {
  "size": 0,
  "query": {
    "match": {
      "_all": "megan'"
    }
  },
  "aggs": {
    "by_session": {
      "terms": {
        "field": "acquisition._id",
        "size": 100
      },
      "aggs": {
        "by_top_hit": {
          "top_hits": {
            "size": 1
          }
        }
      }
    }
  }
}

EXAMPLE_FILE_QUERY = {
  "size": 100,
  "query": {
    "bool": {
      "must": {
        "match": {
          "_all": "brain"
        }
      },
      "filter": {
        "bool" : {
          "must" : [
             { "term" : {"file.type" : "dicom"}},
             { "term" : {"container_type" : "file"}}
          ]
        }
      }
    }
  }
}
"""


ANALYSIS = {
    "analyzer": {
        "my_analyzer": {
            "tokenizer": "my_tokenizer",
            "filter": ["lowercase"]
        }
    },
    "tokenizer": {
        "my_tokenizer": {
            "type": "ngram",
            "min_gram": 2,
            "max_gram": 100,
            "token_chars": [
                "letter",
                "digit",
                "symbol",
                "punctuation"
            ]
        }
    }
}

DYNAMIC_TEMPLATES = [
    {
        'string_fields' : {
            'match': '*',
            'match_mapping_type' : 'string',
            'mapping' : {
                'type': 'text',
                'analyzer': 'my_analyzer',
                'search_analyzer': 'standard',
                'index': True,
                "fields": {
                    "raw": {
                        "type": "keyword",
                        "index": True,
                        "ignore_above": 256
                    }
                }
            }
        }
    }
]

MATCH_ALL= {"match_all": {}}

FACET_QUERY = {
    "size": 0,
    "aggs" : {
        "session_count" : {
            "cardinality" : {
                "field" : "session._id"
            }
        },
        "acquisition_count" : {
            "cardinality" : {
                "field" : "acquisition._id"
            }
        },
        "analysis_count" : {
            "cardinality" : {
                "field" : "analysis._id"
            }
        },
        "file_count" : {
            "cardinality" : {
                "field" : "file._id"
            }
        },
        "by_session": {
            "filter": {"term": {"container_type": "session"}},
            "aggs": {
                "subject.sex" : {
                    "terms" : {
                        "field" : "subject.sex.raw",
                        "size" : 15,
                        "missing": "null"
                    }
                },
                "session.tags" : {
                    "terms" : {
                        "field" : "subject.tags.raw",
                        "size" : 15,
                        "missing": "null"
                    }
                },
                "subject.code" : {
                    "terms" : {
                        "field" : "subject.code.raw",
                        "size" : 15,
                        "missing": "null"
                    }
                },
                "session.timestamp" : {
                    "stats" : { "field" : "session.timestamp"}

                },
            }
        },
        "session_age": {
            "filter": {
                "bool" : {
                  "must" : [
                     {"range": {"subject.age": {"gte": -31556952, "lte": 3155695200}}},
                     {"term": {"container_type": "session"}}
                  ]
                }
            },
            "aggs": {
                "subject.age" : {
                    "histogram" : {
                        "field" : "subject.age",
                        "interval" : 31556952,
                        "extended_bounds" : {
                            "min" : -31556952,
                            "max" : 3155695200
                        }
                    }
                }
            }
        },
        "by_file": {
            "filter": {"term": {"container_type": "file"}},
            "aggs": {

                "file.classification" : {
                    "terms" : {
                        "field" : "file.classification.raw",
                        "size" : 15,
                        "missing": "null"
                    }
                },
                "file.type" : {
                    "terms" : {
                        "field" : "file.type.raw",
                        "size" : 15,
                        "missing": "null"
                    }
                }
            }
        }
    }
}

INFO_EXISTS_SCRIPT = {
    'script': """
        (params['_source'].containsKey('file') &&
        params['_source']['file'].containsKey('info') &&
        !params['_source']['file']['info'].empty)
    """
}


SOURCE_COMMON = [
    "group._id",
    "group.label",
    "permissions",
]

SOURCE_COLLECTION = [
    "permissions",
    "collection._id",
    "collection.label",
    "collection.curator",
    "collection.created",
]

SOURCE_PROJECT = SOURCE_COMMON + [
    "project._id",
    "project.label",
]

SOURCE_SESSION = SOURCE_PROJECT + [
    "session._id",
    "session.created",
    "session.label",
    "session.timestamp",
    "subject.code",
]

SOURCE_ACQUISITION = SOURCE_SESSION + [
    "acquisition._id",
    "acquisition.created",
    "acquisition.label",
    "acquisition.timestamp",
]

SOURCE_ANALYSIS = SOURCE_SESSION + [
    "analysis._id",
    "analysis.created",
    "analysis.label",
    "analysis.user",
    "analysis.parent", # TODO: coalesce analysis and file parent keys (analysis.parent.id vs parent._id for file)
]

SOURCE_FILE = SOURCE_ANALYSIS + [
    "file.created",
    "file.classification",
    "file.name",
    "file.size",
    "file.type",
    "parent",
]

SOURCE = {
    "collection": SOURCE_COLLECTION,
    "project": SOURCE_PROJECT,
    "session": SOURCE_SESSION,
    "acquisition": SOURCE_ACQUISITION,
    "analysis": SOURCE_ANALYSIS,
    "file": SOURCE_FILE
}

# Containers where search doesn't do an aggregation to find results
EXACT_CONTAINERS = ['file', 'collection']


class DataExplorerHandler(base.RequestHandler):
    # pylint: disable=broad-except

    def __init__(self, request=None, response=None):
        super(DataExplorerHandler, self).__init__(request, response)

    def _parse_request(self, request_type='search'):

        try:
            request = self.request.json_body
        except (ValueError):
            if request_type == 'search':
                self.abort(400, 'Must specify return type')
            return None, None, None, 0

        # Parse and validate return_type
        return_type = request.get('return_type')
        if not return_type or return_type not in ['collection', 'project', 'session', 'acquisition', 'analysis', 'file']:
            if request_type == 'search':
                self.abort(400, 'Must specify return type')

        # Parse and "validate" filters, allowed to be non-existent
        filters = request.get('filters', [])
        if type(filters) is not list:
            self.abort(400, 'filters must be a list')

        modified_filters = []

        for f in filters:
            if f.get('terms'):
                for k,v in f['terms'].iteritems():
                    if "null" in v:
                        if isinstance(v, list):
                            v.remove("null")
                        elif isinstance(v, str):
                            v = None
                        null_filter = {
                            'bool': {
                                'should': [
                                    {
                                        'bool': {
                                            'must': [
                                                {
                                                    'bool':{
                                                        'must_not': [
                                                            {
                                                                'exists': {'field': k}
                                                            }
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                        if len(k.split('.')) > 1:
                            null_filter['bool']['should'][0]['bool']['must'].append({'exists': {'field': k.split('.')[0]}})
                        if v:
                            null_filter['bool']['should'].append({'terms': {k+'.raw': v}})
                        modified_filters.append(null_filter)

                    else:
                        modified_filters.append({'terms': {k+'.raw': v}})
            elif f.get('term'):
                # Search raw field
                for k,v in f['term'].iteritems():
                    modified_filters.append({'term': {k+'.raw': v}})
            else:
                modified_filters.append(f)

        # Add permissions filter to list if user is not requesting all data or is superuser
        if not request.get('all_data', False) and not self.superuser_request:
            modified_filters.append({'term': {'permissions._id': self.uid}})

        # Only return objects that have not been marked as deleted
        modified_filters.append({'term': {'deleted': False}})

        # Parse and "validate" search_string, allowed to be non-existent
        search_string = str(request.get('search_string', ''))


        if request_type == 'facet':
            # size is assumed 0 for facets
            return return_type, modified_filters, search_string, 0

        # Determine query size, if size=all figure out max for return type.
        size = self.request.params.get('size')
        if not size:
            size = self.request.json_body.get("size", 100)
        if size == 'all':
            size = self.search_size(return_type, filters=modified_filters)
        elif not isinstance(size, int):
            try:
                size = int(size)
            except ValueError:
                self.abort(400, 'Size must be an int or "all".')

        # Check that size is less than 10,000
        if int(size) > 10000:
            self.abort(400, "Request would return more than 10,000 results. Please add additional filters.")

        return return_type, modified_filters, search_string, size

    @require_login
    def aggregate_field_values(self):
        """
        Return list of type ahead values for a key given a value
        that the user has already started to type in for the value of
        a custom string field or a set of statistics if the field type is
        a number.
        """
        try:
            field_name = self.request.json_body['field_name']
        except (KeyError, ValueError):
            self.abort(400, 'Field name is required')
        filters = [{'term': {'deleted': False}}]
        if not self.superuser_request:
            filters.append({'term': {'permissions._id': self.uid}})
        try:
            field = config.es.get(index='data_explorer_fields', id=field_name, doc_type='flywheel_field')
        except TransportError as e:
            log.warning(e)
            self.abort(404, 'Could not find mapping for field {}.'.format(field_name))
        field_type = field['_source']['type']
        search_string = self.request.json_body.get('search_string', None)


        # If the field type is a string, return a list of type-ahead values
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must" : {
                        "match" : { field_name : search_string}
                    },
                    "filter" : filters
                }
            }
        }
        if not filters:
            # TODO add non-user auth support (#865)
            body['query']['bool'].pop('filter')
        if search_string is None:
            body['query']['bool']['must'] = MATCH_ALL

        if field_type in ['string', 'boolean']:
            body['aggs'] = {
                "results" : {
                    "terms" : {
                        "field" : field_name + ".raw",
                        "size" : 15,
                        "missing": "null"
                    }
                }
            }

        # If it is a number (int, date, or some other type), return various statistics on the values of the field
        elif field_type in ['integer', 'float', 'date']:
            body['aggs'] = {
                "results" : {
                    "stats" : {
                        "field" : field_name
                    }
                }
            }
        else:
            self.abort(400, 'Aggregations are only allowed on string, integer, float, data and boolean fields.')

        aggs = config.es.search(
            index='data_explorer',
            doc_type='flywheel',
            body=body
        )['aggregations']['results']
        return aggs

    @require_login
    def get_facets(self):

        _, filters, search_string, _ = self._parse_request(request_type='facet')

        facets_q = copy.deepcopy(FACET_QUERY)
        facets_q['query'] = self._construct_query(None, search_string, filters, 0)['query']

        # if the query comes back with a return_type agg, remove it
        facets_q['query'].pop('aggs', None)

        aggs = config.es.search(
            index='data_explorer',
            doc_type='flywheel',
            body=facets_q
        )['aggregations']

        # This aggregation needs an extra filter to filter out outliers (only shows ages between -1 and 100)
        # Add it back in to the session aggregation node
        age_node = aggs.pop('session_age')
        aggs['by_session']['subject.age'] = age_node['subject.age']
        return {'facets': aggs}

    def search_size(self, return_type, filters=None):
        body = {
            "size": 0,
            "aggs" : {
                "count" : {
                    "cardinality" : {
                        "field" : return_type + "._id",
                        "precision_threshold": 100000
                    }
                }
            }
        }

        if filters:
            body["query"] = {
                "bool": {
                    "filter": filters
                }
            }
        size = config.es.search(
            index='data_explorer',
            doc_type='flywheel',
            body=body)['aggregations']['count']['value']
        size = int(size*1.02)
        return size

    def get_nodes(self):

        return_type, filters, search_string, size = self._parse_request()
        if return_type == 'file':
            return self.get_file_nodes(return_type, filters, search_string)

        body = self._construct_query(return_type, search_string, filters, size)

        body['aggs']['by_container'].pop('aggs')
        body['_source'] = [return_type + "._id"]

        nodes = []
        results = config.es.search(
            index='data_explorer',
            doc_type='flywheel',
            body=body)['aggregations']['by_container']['buckets']

        for result in results:
            nodes.append({'level': return_type, '_id': result['key']})
        return {'nodes':nodes}

    def get_file_nodes(self, return_type, filters, search_string):

        query = self._construct_file_query(return_type, filters, search_string)['query']

        nodes = []
        results = helpers.scan(client=config.es, query={'query': query}, scroll='5m', size=1000, index='data_explorer', doc_type='flywheel', _source=[return_type+'._id'])
        for result in results:
            nodes.append({'level': return_type, '_id': result['_source'][return_type]['_id']})
        return {'nodes':nodes}


    @require_login
    def search_fields(self):
        field_query = self.request.json_body.get('field')

        es_query = {
            "size": 15,
            "query": {
                "match" : { "name" : field_query }
            }
        }
        try:
            es_results = config.es.search(
                index='data_explorer_fields',
                doc_type='flywheel_field',
                body=es_query
            )
        except TransportError as e:
            config.log.warning('Fields not yet indexed for search: {}'.format(e))
            return []

        results = []
        for result in es_results['hits']['hits']:
            results.append(result['_source'])

        return results


    @require_login
    def search(self):
        return_type, filters, search_string, size = self._parse_request()

        results = self._run_query(self._construct_query(return_type, search_string, filters, size), return_type)

        if self.is_true('simple'):
            #return a list of the results' `_source` key only
            return [x['_source'] for x in results]

        else:
            response = {'results': results}
            if self.is_true('facets'):
                response['facets'] = self.get_facets()
            return response


    ## CONSTRUCTING QUERIES ##

    def _construct_query(self, return_type, search_string, filters, size=100):
        if return_type in EXACT_CONTAINERS:
            return self._construct_exact_query(return_type, search_string, filters, size)

        query = {
            "size": 0,
            "query": {
                "bool": {
                  "must": {
                    "match": {
                      "_all": search_string
                    }
                  },
                  "filter": {
                    "bool" : {
                      "must" : filters
                    }
                  }
                }
            }
        }

        if return_type: # only searches have a return type, not facet queries
            query['aggs'] = {
                "by_container": {
                    "terms": {
                        "field": return_type+"._id",
                        "size": size
                    },
                    "aggs": {
                        "by_top_hit": {
                            "top_hits": {
                                "_source": SOURCE[return_type],
                                "size": 1
                            }
                        }
                    }
                }
            }


        # Add search_string to "match on _all fields" query, otherwise remove unneeded logic
        if not search_string:
            query['query']['bool'].pop('must')

        # Add filters list to filter key on query if exists
        if not filters:
            query['query']['bool'].pop('filter')

        if not search_string and not filters:
            query['query'] = MATCH_ALL

        return query

    def _construct_exact_query(self, return_type, search_string, filters, size=100):
        query = {
          "size": size,
          "_source": SOURCE[return_type],
          "query": {
            "bool": {
              "must": {
                "match": {
                  "_all": ""
                }
              },
              "filter": {
                "bool" : {
                  "must" : [{ "term" : {"container_type" : return_type}}]
                }
              }
            }
          }
        }

        if return_type == 'file':
            query['script_fields'] = {
            "info_exists" : INFO_EXISTS_SCRIPT
        }

        # Add search_string to "match on _all fields" query, otherwise remove unneeded logic
        if search_string:
            query['query']['bool']['must']['match']['_all'] = search_string
        else:
            query['query']['bool'].pop('must')

        # Add filters list to filter key on query if exists
        if filters:
            query['query']['bool']['filter']['bool']['must'].extend(filters)

        return query


    ## RUNNING QUERIES AND PROCESSING RESULTS ##

    def _run_query(self, es_query, result_type):
        try:
            results = config.es.search(
                index='data_explorer',
                doc_type='flywheel',
                body=es_query
            )
        except RequestError:
            self.abort(400, 'Unable to parse filters - invalid format.')

        return self._process_results(results, result_type)

    def _process_results(self, results, result_type):
        if result_type in EXACT_CONTAINERS:
            return self._process_exact_results(results, result_type)
        else:
            containers = results['aggregations']['by_container']['buckets']
            modified_results = []
            for c in containers:
                modified_results.append(c['by_top_hit']['hits']['hits'][0])
            return modified_results

    def _process_exact_results(self, results, result_type):
        results = results['hits']['hits']
        if result_type == 'file':

            # Note: At some point this would be better suited
            # as an indexed field rather than scripted on the fly
            for r in results:
                fields = r.pop('fields', {})
                r['_source']['file']['info_exists'] = fields.get('info_exists')[0]

        return results





### Field mapping index helper functions
    @classmethod
    def _get_field_type(cls, field_type):
        if field_type in ['text', 'keyword']:
            return 'string'
        elif field_type in ['long', 'integer', 'short', 'byte']:
            return 'integer'
        elif field_type in ['double', 'float']:
            return 'float'
        elif field_type in ['date', 'boolean', 'object']:
            return field_type
        else:
            config.log.debug('Didnt recognize this field type {}, setting as string'.format(field_type))

    @classmethod
    def _handle_properties(cls, properties, current_field_name):

        ignore_fields = [
            '_all', 'dynamic_templates', 'analysis_reference', 'file_reference',
            'parent', 'container_type', 'origin', 'permissions', '_id',
            'project_has_template', 'hash'
        ]

        for field_name, field in properties.iteritems():

            # Ignore some fields
            if field_name in ignore_fields:
                continue

            elif 'properties' in field:
                new_curr_field = current_field_name+'.'+field_name if current_field_name != '' else field_name
                cls._handle_properties(field['properties'], new_curr_field)

            else:
                field_type = cls._get_field_type(field['type'])
                facet_status = False
                if field_type == 'object':
                    # empty objects don't get added
                    continue

                field_name = current_field_name+'.'+field_name if current_field_name != '' else field_name

                if field_type == 'string':
                    # if >85% of values fall in top 15 results, mark as a facet
                    body = {
                        "size": 0,
                        "aggs" : {
                            "results" : {
                                "terms" : {
                                    "field" : field_name + ".raw",
                                    "size" : 15
                                }
                            }
                        }
                    }

                    aggs = config.es.search(
                        index='data_explorer',
                        doc_type='flywheel',
                        body=body
                    )['aggregations']['results']

                    other_doc_count = aggs['sum_other_doc_count']
                    facet_doc_count = sum([bucket['doc_count'] for bucket in aggs['buckets']])
                    total_doc_count = other_doc_count+facet_doc_count

                    if other_doc_count == 0 and facet_doc_count > 0:
                        # All values fit in 15 or fewer buckets
                        facet_status = True
                    elif other_doc_count > 0 and facet_doc_count > 0 and (facet_doc_count/total_doc_count) > 0.85:
                        # Greater than 85% of values fit in 15 or fewer buckets
                        facet_status = True
                    else:
                        # There are no values or too diverse of values
                        facet_status = False

                doc = {
                    'name':                 field_name,
                    'type':                 field_type,
                    'facet':                facet_status
                }

                doc_s = json.dumps(doc)
                config.es.index(index='data_explorer_fields', id=field_name, doc_type='flywheel_field', body=doc_s)

    @require_superuser
    def index_field_names(self):

        try:
            if not config.es.indices.exists('data_explorer'):
                self.abort(404, 'data_explorer index not yet available')
        except TransportError as e:
            self.abort(404, 'elastic search not available: {}'.format(e))

        # Sometimes we might want to clear out what is there...
        if self.is_true('hard-reset') and config.es.indices.exists('data_explorer_fields'):
            config.log.debug('Removing existing data explorer fields index...')
            try:
                config.es.indices.delete(index='data_explorer_fields')
            except ElasticsearchException as e:
                self.abort(500, 'Unable to clear data_explorer_fields index: {}'.format(e))

        # Check to see if fields index exists, if not - create it:
        if not config.es.indices.exists('data_explorer_fields'):
            request = {
                'settings': {
                    'number_of_shards': 1,
                    'number_of_replicas': 0,
                    'analysis' : ANALYSIS
                },
                'mappings': {
                    '_default_' : {
                        '_all' : {'enabled' : True},
                        'dynamic_templates': DYNAMIC_TEMPLATES
                    },
                    'flywheel': {}
                }
            }

            config.log.debug('creating data_explorer_fields index ...')
            try:
                config.es.indices.create(index='data_explorer_fields', body=request)
            except ElasticsearchException:
                self.abort(500, 'Unable to create data_explorer_fields index: {}'.format(e))

        try:
            mappings = config.es.indices.get_mapping(index='data_explorer', doc_type='flywheel')
            fw_mappings = mappings['data_explorer']['mappings']['flywheel']['properties']
        except (TransportError, KeyError):
            self.abort(404, 'Could not find mappings, exiting ...')

        self._handle_properties(fw_mappings, '')
