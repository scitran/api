import copy

from . import (
    es_query, add_filter_from_list, add_filter
)
from .. import config

log = config.log

querygraph = {
    'acquisitions': {
        'parents': ['sessions', 'collections'],
    },
    'sessions': {
        'parents': ['projects'],
        'children': ['acquisitions']
    },
    'projects': {
        'parents': ['groups'],
        'children': ['sessions']
    },
    'groups': {
        'children': ['projects']
    },
    'collections': {
        'children': ['acquisitions']
    }
}
_min_score = 1

class SearchContainer(object):

    def __init__(self, cont_name, query, targets):
        self.cont_name = cont_name
        self.query = query
        self.is_target = False
        self.child_targets = set()
        for t in targets:
            if t == cont_name:
                self.is_target = True
            else:
                self.child_targets.add(t)
        log.error(self.child_targets)
        self.results = None

    def get_results(self):
        if self.query is None:
            return
        else:
            self.results = self._exec_query(self.query)
            return self.results

    def _exec_query(self, query):
        q = es_query(query, self.cont_name, _min_score)
        results = config.es.search(
            index='scitran',
            doc_type=self.cont_name,
            body=q,
            size=10000
        )['hits']['hits']
        return {r['_id']: r for r in results}

    def receive(self, source, source_results, from_child=False):
        if source_results is None:
            return
        if from_child and self.cont_name == 'collections':
            filter_on_field = '_id'
            list_ids = []
            for r in source_results.values():
                for _id in r['_source'].get('collections',[]):
                    list_ids.append(_id)
        elif from_child:
            filter_on_field = '_id'
            list_ids = [r['_source'][self.cont_name[:-1]] for r in source_results.values()]
        else:
            filter_on_field = source[:-1] if source != 'collections' else source
            list_ids = source_results.keys()
        if self.results is not None:
            updated_results = {}
            for _id, r in self.results.items():
                if self._to_set(r.get(filter_on_field, [])).intersection(list_ids):
                    updated_results[_id] = r
            self.results = updated_results
        else:
            self.query = add_filter_from_list(self.query, filter_on_field, list_ids)
            self.results = self._exec_query(self.query)

    def _to_set(self, value_or_list):
        if type(value_or_list) == list:
            return set(value_or_list)
        else:
            return set([value_or_list])

    def collect(self):
        if self.is_target:
            if self.results is None:
                self.results = self._exec_query(query={"match_all": {}})
            final_results = {
                self.cont_name: self.results.values()
            }
        else:
            final_results = {}
        for t in self.child_targets:
            log.error(self.cont_name)
            results = t.get_results(self.cont_name, self.results)
            final_results[t.name] = final_results.get(t.name, []) + results.values()
        log.error(final_results)
        return final_results


class TargetProperty(object):

    def __init__(self, name, query):
        self.name = name
        self.query = query

    def _get_results(self, parent_name, parent_results):
        if self.query is None:
            self.query = {"match_all": {}}
        self.query = add_filter(self.query, 'container_name', parent_name)
        if parent_results is not None:
            parent_ids = parent_results.keys()
            self.query = add_filter_from_list(self.query, 'container_id', parent_ids)
        return self._exec_query(self.query)

    def get_results(self, parent_name, parent_results):
        return self._get_results(parent_name, parent_results)

    def _exec_query(self, query):
        q = es_query(query, self.name, _min_score)
        results = config.es.search(
            index='scitran',
            doc_type=self.name,
            body=q,
            size=10000
        )['hits']['hits']
        return {r['_id']: r for r in results}


class PreparedSearch(object):

    containers = ['groups', 'projects', 'sessions', 'collections', 'acquisitions']

    def __init__(self, target_paths, queries):
        self.queries = queries
        self.target_lists = {}
        for path in target_paths:
            targets = self._get_targets(path)
            self._merge_into(targets, self.target_lists)
        self.search_containers = {}
        log.error(self.target_lists)
        for cont_name in self.containers:
            query = self.queries.get(cont_name)
            targets = self.target_lists.get(cont_name, [])
            self.search_containers[cont_name] = SearchContainer(cont_name, query, targets)

    def _get_targets(self, path):
        path_parts = path.split('/')
        query = self.queries.get(path_parts[-1])
        if path_parts[-1] in ['files', 'notes']:
            target = TargetProperty(path_parts[-1], query)
            if len(path_parts) == 1:
                return {
                    c: [copy.deepcopy(target)] for c in self.containers
                }
            else:
                return {path_parts[-min_length-1]: [target]}
        else:
            return {path_parts[-1]: [path_parts[-1]]}

    def _merge_into(self, source_dict, destination):
        for k, elements in source_dict.iteritems():
            destination[k] = destination.get(k, []) + elements

    def process_search(self):
        for cont_name in self.containers:
            container = self.search_containers[cont_name]
            partial_results = container.get_results()
            for child_name in querygraph[cont_name].get('children', []):
                self.search_containers[child_name].receive(
                    cont_name, partial_results
                )
        results = {}
        for cont_name in self.containers[::-1]:
            container = self.search_containers[cont_name]
            new_results = container.collect()
            if new_results:
                log.error(cont_name + str(new_results))
            self._merge_into(new_results, results)
            for parent_name in querygraph[cont_name].get('parents', []):
                self.search_containers[parent_name].receive(
                    cont_name, container.results, from_child=True
                )
        return results
