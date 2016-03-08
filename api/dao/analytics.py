from .. import config

log = config.log

def add(analytics_type, container_id, user_id, user_site, timestamp):
    view = dict(
        analytics_type=analytics_type,
        container_id=container_id,
        user_id=user_id,
        user_site=user_site,
        timestamp=timestamp
    )
    config.db.analytics.insert_one(view)

def get(analytics_type, container_id, user_id, user_site, start_date, end_date, count, limit):
    query = {}
    if user_id:
        query['user_id'] = user_id
        query['user_site'] = user_site
    if analytics_type:
        query['analytics_type'] = analytics_type
    if container_id:
        query['container_id'] = container_id
    date_query = {}
    if start_date:
        date_query['$gte'] = start_date
    if end_date:
        date_query['$lt'] = end_date
    if date_query:
        query['timestamp'] = date_query
    if count:
        return {'count': config.db.analytics.count(query)}
    else:
        return list(config.db.analytics.find(query, limit=limit))
