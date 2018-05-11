from webapp2 import Request

from .. import config
from ..web import base
from ..web.errors import APINotFoundException


# Efficiently search in multiple collections
CONTAINER_SEARCH_JS = r"""
(function searchContainer(_id) {
    if (/^[a-f\d]{24}$/i.test(_id)) {
        _id = ObjectId(_id);
    }
    return {
        "groups": db.getCollection("groups").findOne({"_id" : _id}, {"_id": 1}),
        "projects": db.getCollection("projects").findOne({"_id" : _id}, {"_id": 1}),
        "sessions": db.getCollection("sessions").findOne({"_id" : _id}, {"_id": 1}),
        "acquisitions": db.getCollection("acquisitions").findOne({"_id" : _id}, {"_id": 1}),
        "analyses": db.getCollection("analyses").findOne({"_id" : _id}, {"_id": 1}),
        "collections": db.getCollection("collections").findOne({"_id" : _id}, {"_id": 1})
    }
})("%s");
"""


class AbstractContainerHandler(base.RequestHandler):
    """
    Asbtract handler that removes the need to know a container's noun before performing an action.
    """

    # pylint: disable=unused-argument
    def handle(self, cid, extra):
        """
        Dispatch a request from /containers/x/... to its proper destination.
        For example:
            /containers/x/files --> x is a project ID --> /projects/x/files
        """

        # Run command; check result
        command = config.db.command('eval', CONTAINER_SEARCH_JS % cid)
        result = command.get('retval')

        if command.get('ok') != 1.0 or result is None:
            self.abort(500, 'Error running db command')

        # Find which container type was found, if any
        cont_name = None
        for key in result.keys():
            if result[key] is not None:
                cont_name = key
                break
        else:
            raise APINotFoundException('No container ' + cid + ' found')

        # Create new request instance using destination URI (eg. replace containers with cont_name)
        destination_environ = self.request.environ
        for key in 'PATH_INFO', 'REQUEST_URI':
            destination_environ[key] = destination_environ[key].replace('containers', cont_name, 1)
        destination_request = Request(destination_environ)

        # Apply SciTranRequest attrs
        destination_request.id = self.request.id
        destination_request.logger = self.request.logger

        # Dispatch the destination request
        self.app.router.dispatch(destination_request, self.response)
