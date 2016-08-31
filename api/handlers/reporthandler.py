import bson
import dateutil
import copy

from .. import base
from .. import config

log = config.log

EIGHTEEN_YEARS_IN_SEC = 18 * 365.25 * 24 * 60 * 60

class APIReportException(Exception):
    pass

class ReportHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(ReportHandler, self).__init__(request, response)

    def get(self, report_type):
        report = None
        if report_type == 'site':
            report = SiteReport()

        elif report_type == 'project':
            project_list = self.request.GET.getall('projects')
            start_date = self.get_param('start_date')
            end_date = self.get_param('end_date')

            if len(project_list) < 1:
                self.abort(400, 'List of projects requried for Project Report')
            if start_date is not None:
                start_date = dateutil.parser.parse(self.get_param('start_date'))
            if end_date is not None:
                end_date = dateutil.parser.parse(self.get_param('end_date'))
            if end_date is not None and start_date is not None and end_date < start_date:
                self.abort(400, 'End date {} is before start date {}'.format(end_date, start_date))

            report = ProjectReport([bson.ObjectId(id_) for id_ in project_list],
                                   start_date=start_date,
                                   end_date=end_date)

        else:
            # They should never even get this far because of filtering in api.py
            self.abort(400, 'The report type {} is not supported'.format(report_type))

        if self.superuser_request or report.user_can_generate(self.uid):
            return report.build()
        else:
            self.abort(403, 'User {} does not have required permissions to generate report'.format(self.uid))


def _get_result_list(output):
    """
    Helper function for extracting mongo aggregation results

    Given the output of a mongo aggregation call, checks 'ok' field
    If not 1.0, 'result' field does not exist or 'result' array is empty,
    throws APIReportException
    """

    if output.get('ok', 0) is not 1.0:
        result = output.get('result')
        if result is not None and len(result) > 0:
            return result

    raise APIReportException

def _get_result(output):
    """
    Helper function for extracting a singular mongo aggregation result

    If more than one item is in the results array, throws APIReportException
    """

    results = _get_result_list(output)
    if len(results) == 1:
        return results[0]

    raise APIReportException

class Report(object):

    def user_can_generate(self, uid):
        """
        Check if user has required permissions to generate report
        """
        raise NotImplementedError()

    def build(self):
        """
        Build and return a json report
        """
        raise NotImplementedError()


class SiteReport(Report):
    """
    Report of statistics about the site, generated by Site Managers

    Report includes:
      - number of groups
      - number of projects per group
      - number of sessions per group
    """

    def user_can_generate(self, uid):
        """
        User generating report must be superuser
        """
        if config.db.users.count({'_id': uid, 'root': True}) > 0:
            return True
        return False

    def build(self):
        report = {}

        groups = config.db.groups.find({})
        report['group_count'] = groups.count()
        report['groups'] = []

        for g in groups:
            group = {}
            group['name'] = g.get('name')

            project_ids = [p['_id'] for p in config.db.projects.find({'group': g['_id']}, [])]
            group['project_count'] = len(project_ids)

            group['session_count'] = config.db.sessions.count({'project': {'$in': project_ids}})
            report['groups'].append(group)

        return report


class ProjectReport(Report):
    """
    Report of statistics about a list of projects, generated by
    Project Admins or Group Admins. Will only include a sessions
    created in date range (inclusive) when provided by the client.

    Report includes:
      - Project Name
      - Group Name
      - Project Admin(s)
      - Number of Sessions
      - Unique Subjects
      - Male Subjects
      - Female Subjects
      - Other Subjects
      - Subjects with sex type Other
      - Subjects under 18
      - Subjects over 18
    """

    def __init__(self, projects, start_date=None, end_date=None):
        """
        Initialize a Project Report

        :projects:      a list of project ObjectIds
        :start_date:    ISO formatted timestamp
        :end_date:      ISO formatted timestamp
        """

        super(ProjectReport, self).__init__()
        self.projects = projects
        self.start_date = start_date
        self.end_date = end_date

    def user_can_generate(self, uid):
        """
        User generating report must be admin on all
        """
        perm_count = config.db.projects.count({'_id': {'$in': self.projects},
                                               'permissions._id': uid,
                                               'permissions.access': 'admin'})
        if perm_count == len(self.projects):
            return True
        return False

    def _base_query(self, pid):
        base_query = {'project': pid}

        if self.start_date is not None or self.end_date is not None:
            base_query['created'] = {}
        if self.start_date is not None:
            base_query['created']['$gte'] = self.start_date
        if self.end_date is not None:
            base_query['created']['$lte'] = self.end_date

        return base_query

    def _base_demo_grid(self):
        """
        Constructs a base demographics grid for the project report
        """

        races = [
                    'American Indian or Alaska Native',
                    'Asian',
                    'Native Hawaiian or Other Pacific Islander',
                    'Black or African American',
                    'White',
                    'More Than One Race',
                    'Unknown or Not Reported'
        ]
        ethnicities = [
                    'Not Hispanic or Latino',
                    'Hispanic or Latino',
                    'Unknown or Not Reported'
        ]
        sexes = [
                    'Female',
                    'Male',
                    'Unknown or Not Reported'
        ]

        sexes_obj = dict([(s, 0) for s in sexes])
        eth_obj = dict([(e, copy.deepcopy(sexes_obj)) for e in ethnicities])
        eth_obj['Total'] = 0
        race_obj = dict([(r, copy.deepcopy(eth_obj)) for r in races])
        race_obj['Total'] = copy.deepcopy(eth_obj)

        return race_obj

    def _process_demo_results(self, results):
        """
        Given demographics aggregation results, fill in base demographics grid

        All `null` or unlisted values will be counted as 'Unknown or Not Reported'
        """
        UNR = 'Unknown or Not Reported'
        grid = self._base_demo_grid()
        total = 0

        for r in results:
            try:
                count = int(r['count'])
                cell = r['_id']
                race = cell['race']
                ethnicity = cell['ethnicity']
                sex = cell['sex']
            except Exception as e:
                raise APIReportException('Demographics aggregation was malformed: {}'.format(e))

            # Null or unrecognized values are listed as UNR default
            if race is None or race not in grid:
                race = UNR
            if ethnicity is None or ethnicity not in grid[race]:
                ethnicity = UNR
            if sex is None:
                sex = UNR
            else:
                sex.capitalize() # We store sex as lowercase in the db
            if sex not in grid[race][ethnicity]:
                sex = UNR

            # Tally up
            total += count
            grid[race]['Total'] += count
            grid[race][ethnicity][sex] += count
            grid['Total'][ethnicity][sex] += count

        return grid, total


    def build(self):
        report = {}
        report['projects'] = []

        projects = config.db.projects.find({'_id': {'$in': self.projects}})
        for p in projects:
            project = {}
            project['name'] = p.get('label')
            project['group_name'] = p.get('group')

            # Create list of project admins
            admins = []
            for perm in p.get('permissions', []):
                if perm.get('access') == 'admin':
                    admins.append(perm.get('_id'))
            admin_objs = config.db.users.find({'_id': {'$in': admins}})
            project['admins'] = map(lambda x: x.get('firstname','')+' '+x.get('lastname',''), admin_objs) # pylint: disable=bad-builtin, deprecated-lambda

            base_query = self._base_query(p['_id'])
            project['session_count'] = config.db.sessions.count(base_query)

            # Count subjects
            # Any stats on subjects require an aggregation to group by subject._id
            subject_q = copy.deepcopy(base_query)
            subject_q['subject._id'] = {'$ne': None}

            pipeline = [
                {'$match': subject_q},
                {'$group': {'_id': '$subject._id'}},
                {'$group': {'_id': 1, 'count': { '$sum': 1 }}}
            ]

            result = _get_result(config.db.command('aggregate', 'sessions', pipeline=pipeline))
            project['subjects_count'] = result.get('count', 0)


            # Count subjects by sex
            # Use last sex reporting for subjects with multiple entries
            sex_q = copy.deepcopy(subject_q)
            sex_q['subject.sex'] = {'$ne': None}

            pipeline = [
                {'$match': sex_q},
                {'$group': {'_id': '$subject._id', 'sex': {'$last': '$subject.sex'}}},
                {'$project': {'_id': 1, 'female':  {'$cond': [{'$eq': ['$sex', 'female']}, 1, 0]},
                                        'male':    {'$cond': [{'$eq': ['$sex', 'male']}, 1, 0]},
                                        'other':   {'$cond': [{'$eq': ['$sex', 'other']}, 1, 0]}}},
                {'$group': {'_id': 1, 'female': {'$sum': '$female'},
                                      'male':   {'$sum': '$male'},
                                      'other':  {'$sum': '$other'}}}
            ]
            result = _get_result(config.db.command('aggregate', 'sessions', pipeline=pipeline))

            project['female_count'] = result.get('female',0)
            project['males_count'] = result.get('male',0)
            project['other_count'] = result.get('other',0)


            # Construct grid of subject sex, race and ethnicity
            # Use last sex/race/ethnicity reporting for subjects with multiple entries
            grid_q = copy.deepcopy(subject_q)

            pipeline = [
                {'$match': grid_q},
                {'$group': {'_id': '$subject._id', 'sex':       {'$last': '$subject.sex'},
                                                   'race':      {'$last': '$subject.race'},
                                                   'ethnicity': {'$last': '$subject.ethnicity'}}},
                {'$group': {'_id': { 'sex': '$sex', 'race': '$race', 'ethnicity': '$ethnicity'}, 'count': {'$sum': 1}}}
            ]
            results = _get_result_list(config.db.command('aggregate', 'sessions', pipeline=pipeline))

            grid, total = self._process_demo_results(results)
            project['demographics_grid'] = grid
            project['demographics_total'] = total

            # Count subjects by age group
            # Age is taken as an average over all subject entries
            age_q = copy.deepcopy(subject_q)
            age_q['subject.age'] = {'$gt': 0}

            pipeline = [
                {'$match': age_q},
                {'$group': {'_id': '$subject._id', 'age': { '$avg': '$subject.age'}}},
                {'$project': {'_id': 1, 'over_18':  {'$cond': [{'$gte': ['$age', EIGHTEEN_YEARS_IN_SEC]}, 1, 0]},
                                        'under_18': {'$cond': [{'$lt': ['$age', EIGHTEEN_YEARS_IN_SEC]}, 1, 0]}}},
                {'$group': {'_id': 1, 'over_18': {'$sum': '$over_18'}, 'under_18': {'$sum': '$under_18'}}}
            ]
            result = _get_result(config.db.command('aggregate', 'sessions', pipeline=pipeline))

            project['over_18_count'] = result.get('over_18',0)
            project['under_18_count'] = result.get('under_18',0)


            report['projects'].append(project)

        return report
