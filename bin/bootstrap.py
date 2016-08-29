#!/usr/bin/env python

"""This script helps bootstrap users and data"""

import os
import os.path
import sys
import json
import logging
import argparse
import datetime

import jsonschema

repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
sys.path.append(repo_path)

from api import config, validators

def bootstrap_users_and_groups(bootstrap_json_file_path):
    """Loads users and groups directly into the database.

    Args:
        bootstrap_json_file_path (str): Path to json file with users and groups
    """
    log = logging.getLogger('scitran.bootstrap')
    with open(bootstrap_json_file_path, "r") as bootstrap_data_file:
        bootstrap_data = json.load(bootstrap_data_file)
    user_schema_path = validators.schema_uri("mongo", "user.json")
    user_schema, user_resolver = validators._resolve_schema(user_schema_path)
    for user in bootstrap_data.get("users", []):
        config.log.info("Bootstrapping user: {0}".format(user["email"]))
        user["created"] = user["modified"] = datetime.datetime.utcnow()
        if user.get("api_key"):
            user["api_key"]["created"] = datetime.datetime.utcnow()
        validators._validate_json(user, user_schema, user_resolver)
        config.db.users.insert_one(user)
    group_schema_path = validators.schema_uri("mongo", "group.json")
    group_schema, group_resolver = validators._resolve_schema(group_schema_path)
    for group in bootstrap_data.get("groups", []):
        config.log.info("Bootstrapping group: {0}".format(group["name"]))
        group["created"] = group["modified"] = datetime.datetime.utcnow()
        validators._validate_json(group, group_schema, group_resolver)
        config.db.groups.insert_one(group)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.description = 'Bootstrap SciTran users and groups'
    ap.add_argument('json', help='JSON file containing users and groups')
    args = ap.parse_args()
    bootstrap_users_and_groups(args.json)
