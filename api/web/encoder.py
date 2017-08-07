from pymongo.cursor import Cursor
import bson.objectid
import datetime
import json
import pytz

from ..jobs.jobs import Job

def custom_json_serializer(obj):
    if isinstance(obj, bson.objectid.ObjectId):
        return str(obj)
    elif isinstance(obj, datetime.datetime):
        return pytz.timezone('UTC').localize(obj).isoformat()
    elif isinstance(obj, Job):
        return obj.map()
    elif isinstance(obj, Cursor):
        return list(obj)
    raise TypeError(repr(obj) + " is not JSON serializable") # cover 100


def sse_pack(d):
    """
    Format a map with Server-Sent-Event-meaningful keys into a string for transport.

    Happily borrowed from:      http://taoofmac.com/space/blog/2014/11/16/1940
    For reading on web usage:   http://www.html5rocks.com/en/tutorials/eventsource/basics
    For reading on the format:  https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format
    """

    buffer_ = ''

    for k in ['retry', 'id', 'event', 'data']:
        if k in d.keys():
            buffer_ += '%s: %s\n' % (k, d[k])

    return buffer_ + '\n'

def json_sse_pack(d):
    """
    Variant of sse_pack that will json-encode your data blob.
    """

    d['data'] = json.dumps(d['data'], default=custom_json_serializer)

    return sse_pack(d)
