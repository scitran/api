import json
import sys
import traceback
import webapp2
import webapp2_extras.routes

from . import base
from .jobs.handlers import JobsHandler, JobHandler, GearsHandler, GearHandler, RulesHandler
from . import encoder
from . import root
from . import util
from . import config
from . import centralclient
from . import download
from . import upload
from .handlers import listhandler
from .handlers import userhandler
from .handlers import grouphandler
from .handlers import containerhandler
from .handlers import collectionshandler
from .handlers import searchhandler
from .handlers import schemahandler
from .handlers import reporthandler

log = config.log

class Config(base.RequestHandler):

    def get(self):
        """
        .. http:get:: /api/config

            Return public Scitran configuration information.

            :statuscode 200: no error


            **Example request**:

            .. sourcecode:: http

                GET /api/config HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {"site": {"central_url": "https://sdmc.scitran.io/api", "ssl_cert": null, "api_url": "https://10.240.0.2:443/api", "registered": false, "id": "local", "name": "BaliDemo"}, "modified": "2016-03-31T16:30:00.852000+00:00", "auth": {"id_endpoint": "https://www.googleapis.com/plus/v1/people/me/openIdConnect", "verify_endpoint": "https://www.googleapis.com/oauth2/v1/tokeninfo", "client_id": "949263322061-6q4fqi0m4ihkp1v5n6v8q9bef4gd0f1k.apps.googleusercontent.com", "auth_endpoint": "https://accounts.google.com/o/oauth2/auth"}, "created": "2016-03-31T16:30:00.852000+00:00"}
        """

        return config.get_public_config()

    def get_js(self):
        """
        .. http:get:: /api/config.js

            Return public Scitran configuration information in javascript format.

            :statuscode 200: no error


            **Example request**:

            .. sourcecode:: http

                GET /api/config.js HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: text/html; charset=utf-8
                config = {
                    "auth": {
                        "auth_endpoint": "https://accounts.google.com/o/oauth2/auth",
                        "client_id": "949263322061-6q4fqi0m4ihkp1v5n6v8q9bef4gd0f1k.apps.googleusercontent.com",
                        "id_endpoint": "https://www.googleapis.com/plus/v1/people/me/openIdConnect",
                        "verify_endpoint": "https://www.googleapis.com/oauth2/v1/tokeninfo"
                    },
                    "created": "2016-03-31T16:30:00.852000+00:00",
                    "modified": "2016-03-31T16:30:00.852000+00:00",
                    "site": {
                        "api_url": "https://10.240.0.2:443/api",
                        "central_url": "https://sdmc.scitran.io/api",
                        "id": "local",
                        "name": "BaliDemo",
                        "registered": false,
                        "ssl_cert": null
                    }
        """

        self.response.write(
            'config = ' +
            json.dumps( self.get(), sort_keys=True, indent=4, separators=(',', ': '), default=encoder.custom_json_serializer,) +
            ';'
        )

class Version(base.RequestHandler):

    def get(self):
        """
        .. http:get:: /api/version

            Return database schema in javascript format.

            :statuscode 200: no error


            **Example request**:

            .. sourcecode:: http

                GET /api/version HTTP/1.1
                Host: demo.flywheel.io
                Accept: */*


            **Example response**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: application/json; charset=utf-8
                {"_id": "version", "database": 2}
        """

        return config.get_version()

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
    'site_id_re': '[0-9a-z_]{0,24}',
    # user id regex
    # any length, allowed chars are [0-9a-z.@_-]
    'user_id_re': '[0-9a-z.@_-]*',
    # container name regex
    # possible values are projects, sessions, acquisitions or collections
    'cont_name_re': 'projects|sessions|acquisitions|collections',
    # tag regex
    # length between 3 and 24 characters
    # any character allowed except '/''
    'tag_re': '[^/]{1,32}',
    # filename regex
    # any character allowed except '/'
    'filename_re': '[^/]+',
    # note id regex
    # hexadecimal string exactly of length 24
    'note_id_re': '[0-9a-f]{24}',
    # schema regex
    # example: schema_path/schema.json
    'schema_re': r'[^/.]{3,60}/[^/.]{3,60}\.json'
}

def _format(route):
    return route.format(**routing_regexes)

routes = [
    webapp2.Route(r'/api',                  root.Root),
    webapp2_extras.routes.PathPrefixRoute(r'/api', [
        webapp2.Route(r'/download',         download.Download, handler_method='download', methods=['GET', 'POST'], name='download'),
        webapp2.Route(r'/upload/<strategy:label|uid>',           upload.Upload, handler_method='upload', methods=['POST']),
        webapp2.Route(r'/clean-packfiles',  upload.Upload, handler_method='clean_packfile_tokens', methods=['POST']),
        webapp2.Route(r'/engine',           upload.Upload, handler_method='engine', methods=['POST']),
        webapp2.Route(r'/sites',            centralclient.CentralClient, handler_method='sites', methods=['GET']),
        webapp2.Route(r'/register',         centralclient.CentralClient, handler_method='register', methods=['POST']),
        webapp2.Route(r'/config',           Config, methods=['GET']),
        webapp2.Route(r'/config.js',        Config, handler_method='get_js', methods=['GET']),
        webapp2.Route(r'/version',          Version, methods=['GET']),
    ]),
    webapp2.Route(r'/api/users',            userhandler.UserHandler, handler_method='get_all', methods=['GET']),
    webapp2.Route(r'/api/users',            userhandler.UserHandler, methods=['POST']),
    webapp2_extras.routes.PathPrefixRoute(r'/api/users', [
        webapp2.Route(r'/self',                                 userhandler.UserHandler, handler_method='self', methods=['GET']),
        webapp2.Route(r'/self/avatar',                          userhandler.UserHandler, handler_method='self_avatar', methods=['GET']),
        webapp2.Route(r'/self/key',                             userhandler.UserHandler, handler_method='generate_api_key',methods=['POST']),
        webapp2.Route(_format(r'/<_id:{user_id_re}>'),          userhandler.UserHandler, name='user'),
        webapp2.Route(_format(r'/<uid:{user_id_re}>/groups'),   grouphandler.GroupHandler, handler_method='get_all', methods=['GET'], name='groups'),
        webapp2.Route(_format(r'/<uid:{user_id_re}>/avatar'),   userhandler.UserHandler, handler_method='avatar', methods=['GET'], name='avatar'),
    ]),
    webapp2.Route(r'/api/jobs',             JobsHandler),
    webapp2_extras.routes.PathPrefixRoute(r'/api/jobs', [
        webapp2.Route(r'/next',             JobsHandler, handler_method='next', methods=['GET']),
        webapp2.Route(r'/stats',            JobsHandler, handler_method='stats', methods=['GET']),
        webapp2.Route(r'/reap',             JobsHandler, handler_method='reap_stale', methods=['POST']),
        webapp2.Route(r'/add',              JobsHandler, handler_method='add', methods=['POST']),
        webapp2.Route(r'/<:[^/]+>',         JobHandler,  name='job'),
        webapp2.Route(r'/<:[^/]+>/config.json', JobHandler,  name='job', handler_method='get_config'),
        webapp2.Route(r'/<:[^/]+>/retry',   JobHandler,  name='job', handler_method='retry', methods=['POST']),
    ]),
    webapp2.Route(r'/api/gears',             GearsHandler),
    webapp2_extras.routes.PathPrefixRoute(r'/api/gears', [
        webapp2.Route(r'/<:[^/]+>',         GearHandler,  name='job'),
    ]),
    webapp2.Route(r'/api/rules',             RulesHandler),
    webapp2.Route(r'/api/groups',                                   grouphandler.GroupHandler, handler_method='get_all', methods=['GET']),
    webapp2.Route(r'/api/groups',                                   grouphandler.GroupHandler, methods=['POST']),
    webapp2.Route(_format(r'/api/groups/<_id:{group_id_re}>'),      grouphandler.GroupHandler, name='group_details'),

    webapp2.Route(r'/api/collections/curators',                                         collectionshandler.CollectionsHandler, handler_method='curators', methods=['GET']),
    webapp2.Route(r'/api/collections',                                      collectionshandler.CollectionsHandler, name='colls', handler_method='get_all', methods=['GET']),
    webapp2.Route(r'/api/collections',                                      collectionshandler.CollectionsHandler, methods=['POST']),

    webapp2.Route(_format(r'/api/collections/<cid:{cid_re}>'),              collectionshandler.CollectionsHandler, name='coll_details', methods=['GET', 'PUT', 'DELETE']),
    webapp2.Route(_format(r'/api/collections/<cid:{cid_re}>/sessions'),     collectionshandler.CollectionsHandler, name='coll_ses', handler_method='get_sessions', methods=['GET']),
    webapp2.Route(_format(r'/api/collections/<cid:{cid_re}>/acquisitions'), collectionshandler.CollectionsHandler, name='coll_acq', handler_method='get_acquisitions', methods=['GET']),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>'),                          containerhandler.ContainerHandler, name='cont_list', handler_method='get_all', methods=['GET']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>'),                          containerhandler.ContainerHandler, methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>'),           containerhandler.ContainerHandler, name='cont_details', methods=['GET','PUT','DELETE']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/jobs'),           containerhandler.ContainerHandler, name='cont_jobs', handler_method='get_jobs', methods=['GET']),

    webapp2.Route(_format(r'/api/<cont_name:groups>/<cid:{group_id_re}>/<list_name:roles>'),                                        listhandler.ListHandler, name='group_roles_post'),
    webapp2.Route(_format(r'/api/<cont_name:groups>/<cid:{group_id_re}>/<list_name:roles>/<site:{site_id_re}>/<_id:{user_id_re}>'),    listhandler.ListHandler, name='group_roles', methods=['GET', 'PUT', 'DELETE']),


    webapp2.Route(_format(r'/api/<cont_name:groups>/<cid:{group_id_re}>/<list_name:tags>'),                                      listhandler.TagsListHandler, methods=['POST'], name='tags_post'),
    webapp2.Route(_format(r'/api/<cont_name:groups>/<cid:{group_id_re}>/<list_name:tags>/<value:{tag_re}>'),                     listhandler.TagsListHandler, name='tags'),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:tags>'),                                      listhandler.TagsListHandler, methods=['POST'], name='tags_post'),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:tags>/<value:{tag_re}>'),                     listhandler.TagsListHandler, name='tags'),

    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/packfile-start'),                                     listhandler.FileListHandler, name='packfile-start', handler_method='packfile_start', methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/packfile'),                                     listhandler.FileListHandler, name='packfile', handler_method='packfile', methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/packfile-end'),                                     listhandler.FileListHandler, name='packfile-end', handler_method='packfile_end'),
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
    webapp2.Route(_format(r'/api/search'),                                            searchhandler.SearchHandler, handler_method='advanced_search', name='es_proxy', methods=['POST']),
    webapp2.Route(_format(r'/api/search/files'),                                      searchhandler.SearchHandler, handler_method='get_datatree', name='es_data', methods=['GET']),
    webapp2.Route(_format(r'/api/search/<cont_name:{cont_name_re}>'),                 searchhandler.SearchHandler, name='es_proxy', methods=['GET']),
    webapp2.Route(_format(r'/api/schemas/<schema:{schema_re}>'),                      schemahandler.SchemaHandler, name='schemas', methods=['GET']),
    webapp2.Route(r'/api/report/<report_type:site|project>',                          reporthandler.ReportHandler, methods=['GET']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:analyses>'),
                                                                                      listhandler.AnalysesHandler, name='analysis_post', methods=['POST']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:analyses>/<_id:{cid_re}>'),
                                                                                      listhandler.AnalysesHandler, name='analysis',
                                                                                      methods=['GET', 'DELETE']),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:analyses>/<_id:{cid_re}>/files'),
                                                                                      listhandler.AnalysesHandler, handler_method='download',
                                                                                      methods=['GET'], name='analysis_files'),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:analyses>/<_id:{cid_re}>/files/<name:{filename_re}>'),
                                                                                      listhandler.AnalysesHandler,
                                                                                      handler_method='download', name='analysis_single_file'),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:analyses>/<_id:{cid_re}>/notes'),
                                                                                      listhandler.AnalysesHandler, handler_method='add_note',
                                                                                      methods=['POST'], name='analysis_add_note'),
    webapp2.Route(_format(r'/api/<cont_name:{cont_name_re}>/<cid:{cid_re}>/<list_name:analyses>/<_id:{cid_re}>/notes/<note_id:{cid_re}>'),
                                                                                      listhandler.AnalysesHandler, handler_method='delete_note',
                                                                                      methods=['DELETE'], name='analysis_delete_note'),
]


def dispatcher(router, request, response):
    try:
        rv = router.default_dispatcher(request, response)
        if rv is not None:
            response.write(json.dumps(rv, default=encoder.custom_json_serializer))
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
    except webapp2.HTTPException as e:
        util.send_json_http_exception(response, str(e), e.code)
    except Exception as e: # pylint: disable=broad-except
        if config.get_item('core', 'debug'):
            message = traceback.format_exc()
        else:
            message = 'Internal Server Error'
        util.send_json_http_exception(response, message, 500)

def app_factory(*_, **__):
    # pylint: disable=protected-access,unused-argument

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
