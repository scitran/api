import re
import markdown

from . import base

class Root(base.RequestHandler):

    def head(self):
        """
        .. http:head:: /api

            Confirm endpoint is ready for requests

            :statuscode 200: no error
        """

        pass

    def get(self):
        """
        .. http:get:: /api

            Return API documentation

            :statuscode 200: no error

            **Example request**:

            .. sourcecode:: http

                GET /api HTTP/1.1
                Host: demo.flywheel.io
                Accept: text/html

            **Example response (excerpt)**:

            .. sourcecode:: http

                HTTP/1.1 200 OK
                Vary: Accept-Encoding
                Content-Type: text/html
                <html>
                <head>
                <title>SciTran API</title>
                <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
                <style type="text/css">
                table {width:0%; border-width:1px; padding: 0;border-collapse: collapse;}
                table tr {border-top: 1px solid #b8b8b8; background-color: white; margin: 0; padding: 0;}
                table tr:nth-child(2n) {background-color: #f8f8f8;}
                table thead tr :last-child {width:100%;}
                table tr th {font-weight: bold; border: 1px solid #b8b8b8; background-color: #cdcdcd; margin: 0; padding: 6px 13px;}
                table tr th {font-weight: bold; border: 1px solid #b8b8b8; background-color: #cdcdcd; margin: 0; padding: 6px 13px;}
                table tr td {border: 1px solid #b8b8b8; margin: 0; padding: 6px 13px;}
                table tr th :first-child, table tr td :first-child {margin-top: 0;}
                table tr th :last-child, table tr td :last-child {margin-bottom: 0;}
                </style>
                </head>
                <body style="min-width:900px">
                <form name="username" action="" method="get">
                Username: <input type="text" name="user">
                Root: <input type="checkbox" name="root" value="1">
                <input type="submit" value="Generate Custom Links">
                </form>
                <table>
                <thead>
                <tr>
                <th align="left">Resource</th>
                <th align="left">Description</th>
                </tr>
                </thead>
                <tbody>
                <tr>
                <td align="left"><a href="/api/sites">/sites</a></td>
                <td align="left">local and remote sites</td>
                </tr>
                <tr>
                <td align="left">/download</td>
                <td align="left">download</td>
                </tr>
                <tr>
                <td align="left"><a href="/api/users">/users</a></td>
                <td align="left">list of users</td>
                </tr>

                ...


                <tr>
                <td align="left"><a href="/api/schema/user">/schema/user</a></td>
                <td align="left">user schema</td>
                </tr>
                </tbody>
                </table></body>
                </html>


            :query sort: one of ``hit``, ``created-at``
            :query offset: offset number. default is 0
            :query limit: limit number. default is 30
            :reqheader Accept: the response content type depends on
                              :mailheader:`Accept` header
            :reqheader Authorization: optional OAuth token to authenticate
            :resheader Content-Type: this depends on :mailheader:`Accept`
                                    header of request
        """

        resources = """
            Resource                            | Description
            :-----------------------------------|:-----------------------
            [(/sites)]                          | local and remote sites
            /download                           | download
            [(/users)]                          | list of users
            [(/users/self)]                     | user identity
            [(/users/roles)]                    | user roles
            [(/users/*<uid>*)]                  | details for user *<uid>*
            [(/users/*<uid>*/groups)]           | groups for user *<uid>*
            [(/users/*<uid>*/projects)]         | projects for user *<uid>*
            [(/groups)]                         | list of groups
            /groups/*<gid>*                     | details for group *<gid>*
            /groups/*<gid>*/projects            | list of projects for group *<gid>*
            /groups/*<gid>*/sessions            | list of sessions for group *<gid>*
            [(/projects)]                       | list of projects
            [(/projects/groups)]                | groups for projects
            [(/projects/schema)]                | schema for single project
            /projects/*<pid>*                   | details for project *<pid>*
            /projects/*<pid>*/sessions          | list sessions for project *<pid>*
            [(/sessions)]                       | list of sessions
            [(/sessions/schema)]                | schema for single session
            /sessions/*<sid>*                   | details for session *<sid>*
            /sessions/*<sid>*/move              | move session *<sid>* to a different project
            /sessions/*<sid>*/acquisitions      | list acquisitions for session *<sid>*
            [(/acquisitions/schema)]            | schema for single acquisition
            /acquisitions/*<aid>*               | details for acquisition *<aid>*
            [(/collections)]                    | list of collections
            [(/collections/schema)]             | schema for single collection
            /collections/*<cid>*                | details for collection *<cid>*
            /collections/*<cid>*/sessions       | list of sessions for collection *<cid>*
            /collections/*<cid>*/acquisitions   | list of acquisitions for collection *<cid>*
            [(/schema/group)]                   | group schema
            [(/schema/user)]                    | user schema
            """

        if self.debug and self.uid:
            resources = re.sub(r'\[\((.*)\)\]', r'[\1](/api\1?user=%s&root=%r)' % (self.uid, self.superuser_request), resources)
            resources = re.sub(r'(\(.*)\*<uid>\*(.*\))', r'\1%s\2' % self.uid, resources)
        else:
            resources = re.sub(r'\[\((.*)\)\]', r'[\1](/api\1)', resources)
        resources = resources.replace('<', '&lt;').replace('>', '&gt;').strip()

        self.response.headers['Content-Type'] = 'text/html; charset=utf-8'
        self.response.write('<html>\n')
        self.response.write('<head>\n')
        self.response.write('<title>SciTran API</title>\n')
        self.response.write('<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">\n')
        self.response.write('<style type="text/css">\n')
        self.response.write('table {width:0%; border-width:1px; padding: 0;border-collapse: collapse;}\n')
        self.response.write('table tr {border-top: 1px solid #b8b8b8; background-color: white; margin: 0; padding: 0;}\n')
        self.response.write('table tr:nth-child(2n) {background-color: #f8f8f8;}\n')
        self.response.write('table thead tr :last-child {width:100%;}\n')
        self.response.write('table tr th {font-weight: bold; border: 1px solid #b8b8b8; background-color: #cdcdcd; margin: 0; padding: 6px 13px;}\n')
        self.response.write('table tr th {font-weight: bold; border: 1px solid #b8b8b8; background-color: #cdcdcd; margin: 0; padding: 6px 13px;}\n')
        self.response.write('table tr td {border: 1px solid #b8b8b8; margin: 0; padding: 6px 13px;}\n')
        self.response.write('table tr th :first-child, table tr td :first-child {margin-top: 0;}\n')
        self.response.write('table tr th :last-child, table tr td :last-child {margin-bottom: 0;}\n')
        self.response.write('</style>\n')
        self.response.write('</head>\n')
        self.response.write('<body style="min-width:900px">\n')
        if self.debug and not self.get_param('user'):
            self.response.write('<form name="username" action="" method="get">\n')
            self.response.write('Username: <input type="text" name="user">\n')
            self.response.write('Root: <input type="checkbox" name="root" value="1">\n')
            self.response.write('<input type="submit" value="Generate Custom Links">\n')
            self.response.write('</form>\n')
        self.response.write(markdown.markdown(resources, ['extra']))
        self.response.write('</body>\n')
        self.response.write('</html>\n')
