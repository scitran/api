import sys
import json
import webapp2
import webapp2_extras.routes

from . import base
from . import jobs
from . import root
from . import util
from . import config
from . import centralclient
from . import download
from . import upload
from handlers import listhandler
from handlers import userhandler
from handlers import grouphandler
from handlers import containerhandler
from handlers import collectionshandler

log = config.log

class Config(base.RequestHandler):

    def get(self):
        return config.get_public_config()

    def get_js(self):
        self.response.write(
            'config = ' +
            json.dumps( self.get(), sort_keys=True, indent=4, separators=(',', ': '), default=util.custom_json_serializer,) +
            ';'
        )

#regexes used in routing table:
routing_regexes = {
    # group id regex
    # length between 2 and 32 characters
    # allowed characters are [0-9a-z.@_-] (start and ends only with [0-9a-z])
    'group_id_re': '[0-9a-z][0-9a-z.@_-]{0,30}[0-9a-z]',
    # container id regex
    # hexadecimal string exactly of length 24
    'cid_re': '[0-9a-f]{24}',
    # site id regex
    # length less than 24 characters
    # allowed characters are [0-9a-z]
    'site_id_re': '[0-9a-z]{0,24}',
    # user id regex
    # any length, allowed chars are [0-9a-z.@_-]
    'user_id_re': '[0-9a-z.@_-]*',
    # container name regex
    # possible values are projects, sessions, acquisitions or collections
    'cont_name_re': 'projects|sessions|acquisitions|collections',
    # tag regex
    # length between 3 and 24 characters
    # any character allowed except '/''
    'tag_re': '[^/]{3,24}',
    # filename regex
    # length between 3 and 60 characters
    # any character allowed except '/'
    'filename_re': '[^/]+',
    # note id regex
    # hexadecimal string exactly of length 24
    'note_id_re': '[0-9a-f]{24}'
}

def _format(route):
    return route.format(**routing_regexes)

routes = [
    webapp2.Route(r'/api',                  root.Root),
    webapp2_extras.routes.PathPrefixRoute(r'/api', [
        webapp2.Route(r'/download',         download.Download, handler_method='download', methods=['GET', 'POST'], name='download'),
        webapp2.Route(r'/reaper',           upload.Upload, handler_method='reaper', methods=['POST']),
        webapp2.Route(r'/uploader',         upload.Upload, handler_method='uploader', methods=['POST']),
        webapp2.Route(r'/engine',           upload.Upload, handler_method='engine', methods=['POST']),
        webapp2.Route(r'/sites',            centralclient.CentralClient, handler_method='sites', methods=['GET']),
        webapp2.Route(r'/register',         centralclient.CentralClient, handler_method='register', methods=['POST']),
        webapp2.Route(r'/config',           Config, methods=['GET']),
        webapp2.Route(r'/config.js',        Config, handler_method='get_js', methods=['GET'])
    ]),
    webapp2.Route(r'/api/users',            userhandler.UserHandler, handler_method='get_all', methods=['GET']),
    webapp2.Route(r'/api/users',            userhandler.UserHandler, methods=['POST']),
    webapp2_extras.routes.PathPrefixRoute(r'/api/users', [
        webapp2.Route(r'/self',                                 userhandler.UserHandler, handler_method='self', methods=['GET']),
        webapp2.Route(_format(r'/<_id:{user_id_re}>'),          userhandler.UserHandler, name='user'),
        webapp2.Route(_format(r'/<uid:{user_id_re}>/groups'),   grouphandler.GroupHandler, handler_method='get_all', methods=['GET'], name='groups'),
    ]),
    webapp2.Route(r'/api/jobs',             jobs.Jobs),
    webapp2_extras.routes.PathPrefixRoute(r'/api/jobs', [
        webapp2.Route(r'/next',             jobs.Jobs, handler_method='next', methods=['GET']),
        webapp2.Route(r'/count',            jobs.Jobs, handler_method='count', methods=['GET']),
        webapp2.Route(r'/stats',            jobs.Jobs, handler_method='stats', methods=['GET']),
        webapp2.Route(r'/addTestJob',       jobs.Jobs, handler_method='addTestJob', methods=['GET']),
        webapp2.Route(r'/reap',             jobs.Jobs, handler_method='reap_stale', methods=['POST']),
        webapp2.Route(r'/<:[^/]+>',         jobs.Job,  name='job'),
    ]),
    webapp2.Route(r'/api/groups',                                   grouphandler.GroupHandler, handler_method='get_all', methods=['GET']),
    webapp2.Route(r'/api/groups',                                   grouphandler.GroupHandler, methods=['POST']),
    webapp2.Route(_format(r'/api/groups/<_id:{group_id_re}>'),      grouphandler.GroupHandler, name='group_details'),

    webapp2.Route(r'/api/collections/curators',                                         collectionshandler.CollectionsHandler, handler_method='curators', methods=['GET']),
    webapp2.Route(r'/api/<cont_name:collections>',                                      collectionshandler.CollectionsHandler, name='colls', handler_method='get_all', methods=['GET']),
    webapp2.Route(r'/api/<cont_name:collections>',                                      collectionshandler.CollectionsHandler, methods=['POST']),

    webapp2.Route(_format(r'/api/<cont_name:collections>/<cid:{cid_re}>'),              collectionshandler.CollectionsHandler, name='coll_details', methods=['GET', 'PUT', 'DELETE']),
    webapp2.Route(_format(r'/api/<cont_name:collections>/<cid:{cid_re}>/sessions'),     collectionshandler.CollectionsHandler, name='coll_ses', handler_method='get_sessions', methods=['GET']),
    webapp2.Route(_format(r'/api/<cont_name:collections>/<cid:{cid_re}>/acquisitions'), collectionshandler.CollectionsHandler, name='coll_acq', handler_method='get_acquisitions', methods=['GET']),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>'),                          containerhandler.ContainerHandler, name='cont_list', handler_method='get_all', methods=['GET']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>'),                          containerhandler.ContainerHandler, methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>'),           containerhandler.ContainerHandler, name='cont_details', methods=['GET','PUT','DELETE']),

    webapp2.Route(_format(r'/api/<cont_name:groups>/<cid:{group_id_re}>/<list_name:roles>'),                                        listhandler.ListHandler, name='group_roles_post'),
    webapp2.Route(_format(r'/api/<cont_name:groups>/<cid:{group_id_re}>/<list_name:roles>/<site:{site_id_re}>/<_id:{user_id_re}>'),    listhandler.ListHandler, name='group_roles', methods=['GET', 'PUT', 'DELETE']),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:tags>'),                                      listhandler.ListHandler, methods=['POST'], name='tags_post'),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:tags>/<value:{tag_re}>'),                     listhandler.ListHandler, name='tags'),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:files>'),                                     listhandler.FileListHandler, name='files_post', methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:files>/<name:{filename_re}>'),            listhandler.FileListHandler, name='files'),

    webapp2.Route(_format(r'/api/<cont_name:collections|projects>/<cid:{cid_re}>/<list_name:permissions>'),                                     listhandler.PermissionsListHandler, name='perms_post', methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:collections|projects>/<cid:{cid_re}>/<list_name:permissions>/<site:{site_id_re}>/<_id:{user_id_re}>'), listhandler.PermissionsListHandler, name='perms'),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:notes>'),                                     listhandler.NotesListHandler, name='notes_post', methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:notes>/<_id:{note_id_re}>'),                  listhandler.NotesListHandler, name='notes'),

    webapp2.Route(_format(r'/api/users/<uid:{user_id_re}>/<cont_name:{cont_name_re}>'), containerhandler.ContainerHandler, name='user_conts', handler_method='get_all_for_user', methods=['GET']),

    webapp2.Route(r'/api/projects/groups',                                              containerhandler.ContainerHandler, handler_method='get_groups_with_project', methods=['GET']),

    webapp2.Route(_format(r'/api/<par_cont_name:groups>/<par_id:{group_id_re}>/<cont_name:projects>'),          containerhandler.ContainerHandler, name='cont_sublist_groups', handler_method='get_all', methods=['GET']),
    webapp2.Route(_format(r'/api/<par_cont_name:{cont_name_re}>/<par_id:{cid_re}>/<cont_name:{cont_name_re}>'), containerhandler.ContainerHandler, name='cont_sublist', handler_method='get_all', methods=['GET']),
]


def dispatcher(router, request, response):
    rv = router.default_dispatcher(request, response)
    if rv is not None:
        response.write(json.dumps(rv, default=util.custom_json_serializer))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'


def app_factory(*_, **__):
    # don't use config.get_item() as we don't want to require the database at startup
    application = webapp2.WSGIApplication(routes, debug=config.__config['core']['debug'])
    application.router.set_dispatcher(dispatcher)

    # configure new relic
    if config.__config['core']['newrelic']:
        try:
            import newrelic.agent, newrelic.api.exceptions
            newrelic.agent.initialize(config.__config['core']['newrelic'])
            application = newrelic.agent.WSGIApplicationWrapper(application)
            log.info('New Relic detected and loaded. Monitoring enabled.')
        except ImportError:
            log.critical('New Relic libraries not found.')
            sys.exit(1)
        except newrelic.api.exceptions.ConfigurationError:
            log.critical('New Relic detected, but configuration invalid.')
            sys.exit(1)

    return application
