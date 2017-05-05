import datetime as dt

from ..web import base
from .. import config
from .. import util
from ..auth import require_drone, require_login, require_superuser
from ..dao import containerstorage, APINotFoundException
from ..validators import validate_data

log = config.log

Status = util.Enum('Status', {
    'ok':       'ok',       # Device's last seen time is shorter than expected interval for checkin, no errors listed.
    'missing':  'missing',  # Device's last seen time is longer than the expected interval for checkin, but no errors listed.
    'error':    'error' ,   # Device has errors listed.
    'unknown':  'unknown'   # Device did not set an expected checkin interval.
})


class DeviceHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(DeviceHandler, self).__init__(request, response)
        self.storage = containerstorage.ContainerStorage('devices', use_object_id=False)

    @require_login
    def get(self, device_id):
        return self.storage.get_container(device_id)

    @require_login
    def get_all(self):
        return self.storage.get_all_el(None, None, None)

    @require_drone
    def get_self(self):
        device_id = self.origin.get('id', '')
        return self.storage.get_container(device_id)

    @require_drone
    def post(self):
        device_id = self.origin.get('id', '')
        payload = self.request.json_body
        # Clean this up when validate_data method is fixed to use new schemas
        # POST unnecessary, used to avoid run-time modification of schema
        validate_data(payload, 'device.json', 'input', 'POST', optional=True)

        result = self.storage.update_el(device_id, payload)
        if result.matched_count == 1:
            return {'modified': result.modified_count}
        else:
            raise APINotFoundException('Device with id {} not found, state not updated'.format(device_id))

    # NOTE method not routed in api.py
    @require_superuser
    def delete(self, device_id): # pragma: no cover
        raise NotImplementedError()

    def get_status(self):
        devices = self.storage.get_all_el(None, None, None)
        response = {}
        now = dt.datetime.now()
        for d in devices:
            d_obj = {}
            d_obj['last_seen'] = d.get('last_seen')

            if d.get('errors'):
                d_obj['status'] = str(Status.error)
                d_obj['errors'] = d.get('errors')
                response[d.get('_id')] = d_obj.copy()

            elif not d.get('interval'):
                d_obj['status'] = str(Status.unknown)
                response[d.get('_id')] = d_obj.copy()

            elif (now-d.get('last_seen', now)).seconds > d.get('interval'):
                d_obj['status'] = str(Status.missing)
                response[d.get('_id')] = d_obj.copy()

            else:
                d_obj['status'] = str(Status.ok)
                response[d.get('_id')] = d_obj.copy()

        return response
