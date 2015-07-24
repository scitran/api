import os
import json
import webapp2
import bson.json_util
import webapp2_extras.routes

import apps
import core
import jobs
import users
import projects
import sessions
import acquisitions
import collections_


routes = [
    webapp2.Route(r'/api',                                          core.Core),
    webapp2_extras.routes.PathPrefixRoute(r'/api', [
        webapp2.Route(r'/download',                                 core.Core, handler_method='download', methods=['GET', 'POST'], name='download'),
        webapp2.Route(r'/upload',                                   core.Core, handler_method='upload', methods=['POST']),
        webapp2.Route(r'/reaper',                                   core.Core, handler_method='reaper', methods=['POST']),
        webapp2.Route(r'/sites',                                    core.Core, handler_method='sites', methods=['GET']),
        webapp2.Route(r'/search',                                   core.Core, handler_method='search', methods=['GET', 'POST']),
    ]),
    webapp2.Route(r'/api/users',                                    users.Users),
    webapp2_extras.routes.PathPrefixRoute(r'/api/users', [
        webapp2.Route(r'/count',                                    users.Users, handler_method='count', methods=['GET']),
        webapp2.Route(r'/self',                                     users.User, handler_method='self', methods=['GET']),
        webapp2.Route(r'/roles',                                    users.User, handler_method='roles', methods=['GET']),
        webapp2.Route(r'/schema',                                   users.User, handler_method='schema', methods=['GET']),
        webapp2.Route(r'/<:[^/]+>',                                 users.User, name='user'),
        webapp2.Route(r'/<:[^/]+>/groups',                          users.Groups, name='groups'),
    ]),
    webapp2.Route(r'/api/groups',                                   users.Groups),
    webapp2_extras.routes.PathPrefixRoute(r'/api/groups', [
        webapp2.Route(r'/count',                                    users.Groups, handler_method='count', methods=['GET']),
        webapp2.Route(r'/schema',                                   users.Group, handler_method='schema', methods=['GET']),
        webapp2.Route(r'/<:[^/]+>',                                 users.Group, name='group'),
        webapp2.Route(r'/<:[^/]+>/projects',                        projects.Projects, name='g_projects'),
        webapp2.Route(r'/<gid:[^/]+>/sessions',                     sessions.Sessions, name='g_sessions', methods=['GET']),
    ]),
    webapp2.Route(r'/api/projects',                                 projects.Projects, methods=['GET'], name='projects'),
    webapp2_extras.routes.PathPrefixRoute(r'/api/projects', [
        webapp2.Route(r'/count',                                    projects.Projects, handler_method='count', methods=['GET']),
        webapp2.Route(r'/groups',                                   projects.Projects, handler_method='groups', methods=['GET']),
        webapp2.Route(r'/schema',                                   projects.Project, handler_method='schema', methods=['GET']),
        webapp2.Route(r'/<:[0-9a-f]{24}>',                          projects.Project, name='project'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file',                     projects.Project, handler_method='file', methods=['PUT']),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file/<:[^/]+>',            projects.Project, handler_method='file'),
        webapp2.Route(r'/<pid:[0-9a-f]{24}>/sessions',              sessions.Sessions, name='p_sessions'),
    ]),
    webapp2.Route(r'/api/collections',                              collections_.Collections),
    webapp2_extras.routes.PathPrefixRoute(r'/api/collections', [
        webapp2.Route(r'/count',                                    collections_.Collections, handler_method='count', methods=['GET']),
        webapp2.Route(r'/curators',                                 collections_.Collections, handler_method='curators', methods=['GET']),
        webapp2.Route(r'/schema',                                   collections_.Collection, handler_method='schema', methods=['GET']),
        webapp2.Route(r'/<:[0-9a-f]{24}>',                          collections_.Collection, name='collection'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file',                     collections_.Collection, handler_method='file', methods=['PUT']),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file/<:[^/]+>',            collections_.Collection, handler_method='file'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/sessions',                 collections_.CollectionSessions, name='coll_sessions'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/acquisitions',             collections_.CollectionAcquisitions, name='coll_acquisitions'),
    ]),
    webapp2.Route(r'/api/sessions',                                 sessions.Sessions, methods=['GET'], name='sessions'),
    webapp2_extras.routes.PathPrefixRoute(r'/api/sessions', [
        webapp2.Route(r'/count',                                    sessions.Sessions, handler_method='count', methods=['GET']),
        webapp2.Route(r'/schema',                                   sessions.Session, handler_method='schema', methods=['GET']),
        webapp2.Route(r'/<:[0-9a-f]{24}>',                          sessions.Session, name='session'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file',                     sessions.Session, handler_method='file', methods=['PUT']),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file/<:[^/]+>',            sessions.Session, handler_method='file'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/acquisitions',             acquisitions.Acquisitions, name='acquisitions'),
    ]),
    webapp2_extras.routes.PathPrefixRoute(r'/api/acquisitions', [
        webapp2.Route(r'/count',                                    acquisitions.Acquisitions, handler_method='count', methods=['GET']),
        webapp2.Route(r'/schema',                                   acquisitions.Acquisition, handler_method='schema', methods=['GET']),
        webapp2.Route(r'/<:[0-9a-f]{24}>',                          acquisitions.Acquisition, name='acquisition'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file',                     acquisitions.Acquisition, handler_method='file', methods=['PUT']),
        webapp2.Route(r'/<:[0-9a-f]{24}>/file/<:[^/]+>',            acquisitions.Acquisition, handler_method='file'),
        webapp2.Route(r'/<:[0-9a-f]{24}>/tile',                     acquisitions.Acquisition, handler_method='get_tile', methods=['GET']),
    ]),
    webapp2.Route(r'/api/jobs',                                     jobs.Jobs),
    webapp2_extras.routes.PathPrefixRoute(r'/api/jobs', [
        webapp2.Route(r'/next',                                     jobs.Jobs, handler_method='next', methods=['GET']),
        webapp2.Route(r'/count',                                    jobs.Jobs, handler_method='count', methods=['GET']),
        webapp2.Route(r'/<:[^/]+>',                                 jobs.Job,  name='job'),
    ]),
    webapp2.Route(r'/api/apps',                                     apps.Apps),
    webapp2_extras.routes.PathPrefixRoute(r'/api/apps', [
        webapp2.Route(r'/count',                                    apps.Apps, handler_method='count', methods=['GET']),
        webapp2.Route(r'/<:[^/]+>',                                 apps.App,  name='job'),
        webapp2.Route(r'/<:[^/]+>/file',                            apps.App,  handler_method='get_file'),
    ]),
]

def dispatcher(router, request, response):
    rv = router.default_dispatcher(request, response)
    if rv is not None:
        response.write(json.dumps(rv, default=bson.json_util.default))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'

app = webapp2.WSGIApplication(routes)
app.router.set_dispatcher(dispatcher)
