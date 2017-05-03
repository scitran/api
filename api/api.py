import webapp2
import webapp2_extras.routes

from .centralclient               import CentralClient
from .download                    import Download
from .handlers.collectionshandler import CollectionsHandler
from .handlers.confighandler      import Config, Version
from .handlers.containerhandler   import ContainerHandler
from .handlers.devicehandler      import DeviceHandler
from .handlers.modalityhandler    import ModalityHandler
from .handlers.grouphandler       import GroupHandler
from .handlers.listhandler        import AnalysesHandler, ListHandler, FileListHandler, NotesListHandler, PermissionsListHandler, TagsListHandler
from .handlers.reporthandler      import ReportHandler
from .handlers.resolvehandler     import ResolveHandler
from .handlers.roothandler        import RootHandler
from .handlers.schemahandler      import SchemaHandler
from .handlers.searchhandler      import SearchHandler
from .handlers.userhandler        import UserHandler
from .jobs.handlers               import BatchHandler, JobsHandler, JobHandler, GearsHandler, GearHandler, RulesHandler, RuleHandler
from .upload                      import Upload
from .web.base                    import RequestHandler
from . import config
log = config.log

routing_regexes = {

    # Group ID: 2-32 characters of form [0-9a-z.@_-]. Start and ends with alphanum.
    'gid': '[0-9a-z][0-9a-z.@_-]{0,30}[0-9a-z]',

    # Container ID: 24-character hex
    'cid': '[0-9a-f]{24}',

    # Site ID: <= 24-character alphanum
    'sid': '[0-9a-z_]{0,24}',

    # User ID: any length, [0-9a-z.@_-]
    'uid': '[0-9a-zA-Z.@_-]*',

    # Container name
    'cname': 'projects|sessions|acquisitions|collections',

    # Tag name
    'tag': '[^/]{1,32}',

    # Filename
    'fname': '[^/]+',

    # Note ID
    'nid': '[0-9a-f]{24}',

    # Schema path
    'schema': r'[^/.]{3,60}/[^/.]{3,60}\.json'
}

def route(path, target, h=None, m=None, name=None):

    # https://webapp2.readthedocs.io/en/latest/api/webapp2.html#webapp2.Route
    return webapp2.Route(
        # re.compile(path)
        path.format(**routing_regexes),
        target,
        handler_method=h,
        methods=m,
        name=name
    )

def prefix(path, routes):

    # https://webapp2.readthedocs.io/en/latest/api/webapp2_extras/routes.html#webapp2_extras.routes.PathPrefixRoute
    return webapp2_extras.routes.PathPrefixRoute(
        path.format(**routing_regexes),
        routes
    )

endpoints = [
    route('/api',                  RootHandler),
    prefix('/api', [

        # System configuration

        route('/config',           Config,              m=['GET']),
        route('/config.js',        Config,  h='get_js', m=['GET']),
        route('/version',          Version,             m=['GET']),


        # General-purpose upload & download

        route('/download',                                      Download, h='download',              m=['GET', 'POST']),
        route('/upload/<strategy:label|uid|uid-match|reaper>',  Upload,   h='upload',                m=['POST']),
        route('/clean-packfiles',                               Upload,   h='clean_packfile_tokens', m=['POST']),
        route('/engine',                                        Upload,   h='engine',                m=['POST']),


        # Top-level endpoints

        route('/login',                                         RequestHandler, h='log_in',   m=['POST']),
        route('/logout',                                        RequestHandler, h='log_out',  m=['POST']),
        route('/resolve',                                       ResolveHandler, h='resolve',  m=['POST']),
        route('/schemas/<schema:{schema}>',                     SchemaHandler,                m=['GET']),
        route('/report/<report_type:site|project|accesslog|usage>',   ReportHandler,                m=['GET']),


        # Search

        route('/search',                     SearchHandler, h='advanced_search',        m=['POST']),
        route('/search/field',               SearchHandler, h='get_terms_for_field',    m=['POST']),
        route('/search/files',               SearchHandler, h='get_datatree',           m=['GET']),
        route('/search/<cont_name:{cname}>', SearchHandler,                             m=['GET']),


        # Users

        route( '/users',                   UserHandler, h='get_all', m=['GET']),
        route( '/users',                   UserHandler,              m=['POST']),
        prefix('/users', [
            route('/self',                 UserHandler, h='self',            m=['GET']),
            route('/self/avatar',          UserHandler, h='self_avatar',     m=['GET']),
            route('/self/key',             UserHandler, h='generate_api_key',m=['POST']),

            route('/<_id:{uid}>',                       UserHandler),
            route('/<uid:{uid}>/groups',                GroupHandler,                h='get_all',               m=['GET']),
            route('/<uid:{uid}>/avatar',                UserHandler,                 h='avatar',                m=['GET']),
            route('/<uid:{uid}>/reset-registration',    UserHandler,                 h='reset_registration',    m=['POST']),
            route('/<uid:{uid}>/<cont_name:{cname}>',   ContainerHandler, h='get_all_for_user', m=['GET']),

        ]),


        # Jobs & gears

        route( '/jobs',                    JobsHandler),
        prefix('/jobs', [
            route('/next',                 JobsHandler, h='next',       m=['GET']),
            route('/stats',                JobsHandler, h='stats',      m=['GET']),
            route('/reap',                 JobsHandler, h='reap_stale', m=['POST']),
            route('/add',                  JobsHandler, h='add',        m=['POST']),
            route('/<:[^/]+>',             JobHandler),
            route('/<:[^/]+>/config.json', JobHandler,  h='get_config'),
            route('/<:[^/]+>/retry',       JobHandler,  h='retry',      m=['POST']),
            route('/<:[^/]+>/logs',        JobHandler,  h='get_logs',   m=['GET']),
            route('/<:[^/]+>/logs',        JobHandler,  h='add_logs',   m=['POST']),
        ]),
        route('/gears',                                  GearsHandler),
        prefix('/gears', [
            route('/<:[^/]+>',                           GearHandler),
            route('/<:[^/]+>/invocation',                GearHandler, h='get_invocation'),
            route('/<:[^/]+>/suggest/<:[^/]+>/<:[^/]+>', GearHandler, h='suggest'),
        ]),


        # Batch jobs

        route('/batch',                 BatchHandler,   h='get_all',    m=['GET']),
        route('/batch',                 BatchHandler,                   m=['POST']),
        prefix('/batch', [
            route('/<:[^/]+>',          BatchHandler,   h='get',        m=['GET']),
            route('/<:[^/]+>/run',      BatchHandler,   h='run',        m=['POST']),
            route('/<:[^/]+>/cancel',   BatchHandler,   h='cancel',     m=['POST']),
            route('/<:[^/]+>/jobs',     BatchHandler,   h='get_jobs',   m=['GET'])
        ]),


        # Devices

        route( '/devices',              DeviceHandler, h='get_all',    m=['GET']),
        route( '/devices',              DeviceHandler,                 m=['POST']),
        prefix('/devices', [
            route('/status',            DeviceHandler, h='get_status', m=['GET']),
            route('/self',              DeviceHandler, h='get_self',   m=['GET']),
            route('/<device_id:[^/]+>', DeviceHandler,                 m=['GET']),
        ]),

        # Modalities

        route( '/modalities',               ModalityHandler, h='get_all',    m=['GET']),
        route( '/modalities',               ModalityHandler,                 m=['POST']),
        prefix('/modalities', [
            route('/<modality_name:[^/]+>', ModalityHandler,                 m=['GET', 'PUT', 'DELETE']),
        ]),


        # Groups

        route('/groups',             GroupHandler, h='get_all', m=['GET']),
        route('/groups',             GroupHandler,              m=['POST']),
        route('/groups/<_id:{gid}>', GroupHandler,              m=['GET', 'DELETE', 'PUT']),

        prefix('/<cont_name:groups>', [
            route('/<cid:{gid}>/<list_name:roles>',                          ListHandler,     m=['POST']),
            route('/<cid:{gid}>/<list_name:roles>/<site:{sid}>/<_id:{uid}>', ListHandler,     m=['GET', 'PUT', 'DELETE']),

            route('/<cid:{gid}>/<list_name:tags>',                           TagsListHandler, m=['POST']),
            route('/<cid:{gid}>/<list_name:tags>/<value:{tag}>',             TagsListHandler, m=['GET', 'PUT', 'DELETE']),
        ]),


        # Projects

        prefix('/projects', [
            route('/groups',               ContainerHandler, h='get_groups_with_project',      m=['GET']),
            route('/recalc',               ContainerHandler, h='calculate_project_compliance', m=['POST']),
            route('/<cid:{cid}>/template', ContainerHandler, h='set_project_template',         m=['POST']),
            route('/<cid:{cid}>/template', ContainerHandler, h='delete_project_template',      m=['DELETE']),
            route('/<cid:{cid}>/recalc',   ContainerHandler, h='calculate_project_compliance', m=['POST']),
            route('/<cid:{cid}>/rules',    RulesHandler,                                       m=['GET', 'POST']),
            route('/<cid:{cid}>/rules/<rid:{cid}>',  RuleHandler,                              m=['GET', 'PUT', 'DELETE']),
        ]),


        # Sessions

        prefix('/sessions', [
            route('/<cid:{cid}>/jobs',          ContainerHandler, h='get_jobs',     m=['GET']),
            route('/<cid:{cid}>/subject',       ContainerHandler, h='get_subject',  m=['GET']),
        ]),


        # Collections

        route( '/collections',                 CollectionsHandler, h='get_all',                    m=['GET']),
        route( '/collections',                 CollectionsHandler,                                 m=['POST']),
        prefix('/collections', [
            route('/curators',                 CollectionsHandler, h='curators',                   m=['GET']),
            route('/<cid:{cid}>',              CollectionsHandler,                                 m=['GET', 'PUT', 'DELETE']),
            route('/<cid:{cid}>/sessions',     CollectionsHandler, h='get_sessions',               m=['GET']),
            route('/<cid:{cid}>/acquisitions', CollectionsHandler, h='get_acquisitions',           m=['GET']),
        ]),


        # Collections / Projects

        prefix('/<cont_name:collections|projects>', [
            prefix('/<cid:{cid}>', [
                route('/<list_name:permissions>',                          PermissionsListHandler, m=['POST']),
                route('/<list_name:permissions>/<site:{sid}>/<_id:{uid}>', PermissionsListHandler, m=['GET', 'PUT', 'DELETE']),
            ]),
        ]),


        # Containers

        route('/<cont_name:{cname}>', ContainerHandler, name='cont_list', h='get_all', m=['GET']),
        route('/<cont_name:{cname}>', ContainerHandler, m=['POST']),

        prefix('/<cont_name:{cname}>', [
            route('/<cid:{cid}>',                          ContainerHandler,                    m=['GET','PUT','DELETE']),

            prefix('/<cid:{cid}>', [

                route('/<list_name:tags>',                      TagsListHandler,                     m=['POST']),
                route('/<list_name:tags>/<value:{tag}>',        TagsListHandler,                     m=['GET', 'PUT', 'DELETE']),

                route('/packfile-start',                        FileListHandler, h='packfile_start', m=['POST']),
                route('/packfile',                              FileListHandler, h='packfile',       m=['POST']),
                route('/packfile-end',                          FileListHandler, h='packfile_end'),
                route('/<list_name:files>',                     FileListHandler,                     m=['POST']),
                route('/<list_name:files>/<name:{fname}>',      FileListHandler,                     m=['GET', 'DELETE', 'PUT']),
                route('/<list_name:files>/<name:{fname}>/info', FileListHandler, h='get_info',       m=['GET']),


                route('/<list_name:analyses>', AnalysesHandler, m=['POST']),
                # Could be in a prefix. Had weird syntax highlighting issues so leaving for another day
                route('/<list_name:analyses>/<_id:{cid}>',                       AnalysesHandler,                  m=['GET', 'DELETE']),
                route('/<list_name:analyses>/<_id:{cid}>/files',                 AnalysesHandler, h='download',    m=['GET']),
                route('/<list_name:analyses>/<_id:{cid}>/files/<name:{fname}>',  AnalysesHandler, h='download',    m=['GET']),
                route('/<list_name:analyses>/<_id:{cid}>/notes',                 AnalysesHandler, h='add_note',    m=['POST']),
                route('/<list_name:analyses>/<_id:{cid}>/notes/<note_id:{cid}>', AnalysesHandler, h='delete_note', m=['DELETE']),
                route('/<list_name:notes>',                                      NotesListHandler,                 m=['POST']),
                route('/<list_name:notes>/<_id:{nid}>',                          NotesListHandler, name='notes',   m=['GET', 'PUT', 'DELETE']),
            ])
        ]),


        # Misc (to be cleaned up later)

        route('/<par_cont_name:groups>/<par_id:{gid}>/<cont_name:projects>', ContainerHandler, h='get_all', m=['GET']),
        route('/<par_cont_name:{cname}>/<par_id:{cid}>/<cont_name:{cname}>', ContainerHandler, h='get_all', m=['GET']),


        # Multi - site
        route('/sites',    CentralClient, h='sites',    m=['GET']),
        route('/register', CentralClient, h='register', m=['POST']),

    ]),
]
