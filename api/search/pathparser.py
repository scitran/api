"""
The purpose of this module is to parse a query path
(expected in a xpath-like format).
we use only "/" and "//" to indicate respectively children and generic descendants.

Examples:
"collections/sessions/acquisitions/files" and "collections//acquisitions/files"
will prepare a search for files in an acquisition in a collection

"collections//files"
a search for files in collections, sessions and acquisitions (belonging to a collections)

"acquisitions" and "projects//acquisitions"
a search for acquisitions (as incidentally every acquisition is included in a project)

"""
from collections import deque as Queue

class PathNotValidException(Exception):
    pass


class PathParser:

    _search_graph = {
        'collections': ['sessions', 'notes', 'files'],
        'groups': ['projects'],
        'projects': ['sessions', 'notes', 'files'],
        'sessions': ['acquisitions', 'notes', 'files'],
        'acquisitions': ['notes', 'files']
    }

    def __init__(self, path):
        self.path = path
        self.nodes = path.split('/')
        if not (self.nodes[0]):
            raise PathNotValidException('Invalid search path: {}'.format(self.path))
        self.paths = []
        self.prev_node = None
        self.gap = False
        self.final = False
        for n in self.nodes:
            self._parse_one(n)

    def _join(self, paths):
        joined_paths = []
        for p in self.paths:
            for p1 in paths:
                joined_paths.append(p + p1)
        self.paths = joined_paths


    def _parse_one(self, node):
        if self.final == True:
            raise PathNotValidException('Invalid search path: {}'.format(self.path))
        if self.gap == True:
            if node == '':
                self._join(self._expand_all(self.prev_node))
                self.final = True
            else:
                self._join(self._expand_gap(self.prev_node, node))
                self.prev_node = node
            self.gap = False
        elif node == '':
            self.gap = True
        else:
            if not self.paths:
                self.paths = [node]
            else:
                self._join(['/' + node])
            self.prev_node = node

    @staticmethod
    def _expand_gap(root, end):
        q = Queue()
        q.append((root, ''))
        paths = []
        while q:
            node, path = q.popleft()
            if node == end:
                paths.append(path)
            else:
                for c in PathParser._search_graph.get(node, []):
                    q.append((c, path + '/' + c))
        return paths

    @staticmethod
    def _expand_all(root):
        q = Queue()
        q.append((root, ''))
        paths = []
        while q:
            node, path = q.popleft()
            paths.append(path)
            for c in PathParser._search_graph.get(node, []):
                q.append((c, path + '/' + c))
        return paths

