import copy
import json

from ..web import base
from .. import config
from ..auth import require_login, require_superuser

log = config.log

ANALYSIS = {
    "analyzer": {
        "my_analyzer": {
            "tokenizer": "my_tokenizer"
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
                "fields": {
                    "raw": {
                        "type": "keyword",
                        "index": "not_analyzed",
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
        "file_count" : {
            "cardinality" : {
                "field" : "file.name.raw"
            }
        },
        "by_session": {
            "filter": {"term": {"container_type": "session"}},
            "aggs": {
                "subject.sex" : {
                    "terms" : {
                        "field" : "subject.sex.raw",
                        "size" : 15
                    }
                },
                "subject.code" : {
                    "terms" : {
                        "field" : "subject.code.raw",
                        "size" : 15
                    }
                },
                "session.timestamp" : {
                    "stats" : { "field" : "session.timestamp"}

                }
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

                "file.measurements" : {
                    "terms" : {
                        "field" : "file.measurements.raw",
                        "size" : 15
                    }
                },
                "file.type" : {
                    "terms" : {
                        "field" : "file.type.raw",
                        "size" : 15
                    }
                }
            }
        }
    }
}

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


class DataExplorerHandler(base.RequestHandler):
    # pylint: disable=broad-except

    def __init__(self, request=None, response=None):
        super(DataExplorerHandler, self).__init__(request, response)

    def _parse_request(self, request_type='search'):

        try:
            request = self.request.json_body
        except Exception:
            if request_type == 'search':
                self.abort(400, 'Must specify return type')
            return None, None, None

        # Parse and validate return_type
        return_type = request.get('return_type')
        if not return_type or return_type not in ['file', 'session', 'acquisition', 'analysis']:
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
                    modified_filters.append({'terms': {k+'.raw': v}})
            else:
                modified_filters.append(f)

        # Add permissions filter to list if user is not requesting all data
        if not request.get('all_data', False):
            modified_filters.append({'term': {'permissions._id': self.uid}})

        # Parse and "validate" search_string, allowed to be non-existent
        search_string = request.get('search_string', '')
        try:
            search_string = str(search_string)
        except Exception:
            self.abort(400, 'search_string must be of type string')

        return return_type, modified_filters, search_string

    @require_login
    def custom_field_values(self):
        """
        Return list of type ahead values for a key given a value 
        that the user has already started to type in for the value of 
        a custom string field or a set of statistics if the field type is
        a number.
        """
        
        custom_field = self.request.json_body['field_name']
        filters = [{'term': {'permissions._id': self.uid}}]
        field = config.es.indices.get_field_mapping(custom_field,
                                                    index='data_explorer',
                                                    doc_type='flywheel')['data_explorer']['mappings']['flywheel'][custom_field]
        field_type = self._get_field_type(field['mapping'][custom_field.split('.')[-1]]['type'])

        # If the field type is a string, return a list of type-ahead values
        if field_type == 'string':
            user_value = self.request.json_body['value']
            body = {
                "size": 0, 
                "query": {
                    "bool": {
                        "must" : {
                            "match" : { custom_field : user_value}
                        },
                        "filter" : filters
                    }
                },
                "aggs" : {
                    "results" : {
                        "terms" : {
                            "field" : custom_field + ".raw",
                            "size" : 15
                        }
                    }
                }
            }

            if not filters:
                body['query']['bool'].pop('filter')

            aggs = config.es.search(
                index='data_explorer',
                doc_type='flywheel',
                body=body
            )['aggregations']['results']['buckets']
            aggs = [bucket['key'] for bucket in aggs]
            return {'type_aheads': aggs}

        # If it is a number (int, date, or some other type), return various statistics on the values of the field
        else:
            body = {
                "size": 0, 
                "query": {
                    "bool": {
                        "must" : {
                            "match_all" : {}
                        },
                        "filter" :  filters  
                    }
                },
                "aggs" : {
                    "results" : {
                        "stats" : {
                            "field" : custom_field
                        }
                    }
                }
            }
            if not filters:
                body['query']['bool'].pop('filter')

            aggs = config.es.search(
                index='data_explorer',
                doc_type='flywheel',
                body=body
            )['aggregations']['results']

            return aggs          

    @require_login
    def get_facets(self):

        return_type, filters, search_string = self._parse_request(request_type='facet')

        facets_q = copy.deepcopy(FACET_QUERY)
        facets_q['query'] = self._construct_query(return_type, search_string, filters)['query']

        # if the query comes back with a return_type agg, remove it
        facets_q['query'].pop('aggs', None)

        config.log.debug(facets_q)

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

    @require_login
    def search_fields(self):
        field_query = self.request.json_body.get('field')

        try:
            field_query = str(field_query)
        except ValueError:
            self.abort(400, 'Must specify string for field query')

        es_query = {
            "size": 20,
            "query": {
                "match" : { "name" : field_query }
            }
        }
        es_results = config.es.search(
            index='data_explorer_fields',
            doc_type='flywheel_field',
            body=es_query
        )

        results = []
        for result in es_results['hits']['hits']:
            results.append(result['_source'])

        return results


    @require_login
    def search(self):
        return_type, filters, search_string = self._parse_request()
        size = self.request.params.get('size', 100)
        results = self._run_query(self._construct_query(return_type, search_string, filters, size), return_type)
        response = {'results': results}
        if self.is_true('facets'):
            response['facets'] = self.get_facets()
        return response


    ## CONSTRUCTING QUERIES ##

    def _construct_query(self, return_type, search_string, filters, size=100):
        if return_type == 'file':
            return self._construct_file_query(search_string, filters, size)

        source = [ "permissions.*", "session._id", "session.label", "session.created", "session.timestamp",
                   "subject.code", "project.label", "group.label", "group._id", "project._id", "session.archived", "project.archived" ]

        if return_type == 'acquisition':
            source.extend(["acquisition._id", "acquisition.label", "acquisition.created", "acquisition.timestamp", "acquisition.archived"])

        if return_type == 'analysis':
            source.extend(["analysis._id", "analysis.label", "analysis.created"])

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
                                "_source": source,
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

    def _construct_file_query(self, search_string, filters, size=100):
        source = [ "permissions.*", "session._id", "session.label", "session.created",
        "session.timestamp", "subject.code", "project.label", "group.label", "acquisition.label",
        "acquisition._id", "group._id", "project._id", "analysis._id", "analysis.label",
        "session.archived", "acquisition.archived", "project.archived" ]
        source.extend(["file.name", "file.created", "file.type", "file.measurements", "file.size", "parent"])
        query = {
          "size": size,
          "_source": source,
          "query": {
            "bool": {
              "must": {
                "match": {
                  "_all": ""
                }
              },
              "filter": {
                "bool" : {
                  "must" : [{ "term" : {"container_type" : "file"}}]
                }
              }
            }
          }
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
        config.log.debug(es_query)
        results = config.es.search(
            index='data_explorer',
            doc_type='flywheel',
            body=es_query
        )
        return self._process_results(results, result_type)

    def _process_results(self, results, result_type):
        if result_type == 'file':
            return self._process_file_results(results)
        else:
            containers = results['aggregations']['by_container']['buckets']
            modified_results = []
            for c in containers:
                modified_results.append(c['by_top_hit']['hits']['hits'][0])
            return modified_results

    def _process_file_results(self, results):
        return results['hits']['hits']





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

        for field_name, field in properties.iteritems():

            # Ignore some fields
            if field_name in ['_all', 'dynamic_templates', 'analysis_reference', 'file_reference', 'parent', 'container_type', 'origin', 'permissions', '_id']:
                continue

            elif 'properties' in field:
                new_curr_field = current_field_name+'.'+field_name if current_field_name != '' else field_name
                cls._handle_properties(field['properties'], new_curr_field)

            else:
                field_type = cls._get_field_type(field['type'])
                if field_type == 'object':
                    # empty objects don't get added
                    continue

                field_name = current_field_name+'.'+field_name if current_field_name != '' else field_name

                doc = {
                    'name':                 field_name,
                    'type':                 field_type
                }

                doc_s = json.dumps(doc)
                config.es.index(index='data_explorer_fields', id=field_name, doc_type='flywheel_field', body=doc_s)

    @require_superuser
    def index_field_names(self):

        if not config.es.indices.exists('data_explorer'):
            self.abort(404, 'data_explorer index not yet available')

        # Sometimes we might want to clear out what is there...
        if self.is_true('hard-reset') and config.es.indices.exists('data_explorer_fields'):
            config.log.debug('Removing existing data explorer fields index...')
            try:
                config.es.indices.delete(index='data_explorer_fields')
            except Exception:
                self.abort(500, 'Unable to clear data_explorer_fields index.')

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
            except Exception:
                self.abort(500, 'Unable to create data_explorer_fields index')

        try:
            mappings = config.es.indices.get_mapping(index='data_explorer', doc_type='flywheel')
            fw_mappings = mappings['data_explorer']['mappings']['flywheel']['properties']
        except Exception:
            self.abort(404, 'Could not find mappings, exiting ...')

        self._handle_properties(fw_mappings, '')
