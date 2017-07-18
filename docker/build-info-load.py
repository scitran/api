"""
Loads the build info into the version document in the database.
"""
import json
import os
import pymongo
db_uri = os.getenv('SCITRAN_PERSISTENT_DB_URI')
db = pymongo.MongoClient(db_uri).get_default_database()

with open('/version.json') as f:
    build = json.load(f)
db.singletons.find_one_and_update({"_id": "version"}, {'$set' : {'build' : build}})
