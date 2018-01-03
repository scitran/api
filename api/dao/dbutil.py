import random
import time

from pymongo.errors import DuplicateKeyError
from ..web.errors import APIStorageException


def try_replace_one(db, coll_name, query, update, upsert=False):
    """
    Mongo does not see replace w/ upsert as an atomic action:
    https://jira.mongodb.org/browse/SERVER-14322

    This function will try a replace_one operation, returning the result and if the operation succeeded.
    """

    try:
        result = db[coll_name].replace_one(query, update, upsert=upsert)
    except DuplicateKeyError:
        return result, False
    else:
        return result, True


def fault_tolerant_replace_one(db, coll_name, query, update, upsert=False):
    """
    Like try_replace_one, but will retry several times, waiting a random short duration each time.

    Raises an APIStorageException if the retry loop gives up.
    """

    attempts = 0
    while attempts < 10:
        attempts += 1

        result, success = try_replace_one(db, coll_name, query, update, upsert)

        if success:
            return result
        else:
            time.sleep(random.uniform(0.01,0.05))

    raise APIStorageException('Unable to replace object.')


def try_update_one(db, coll_name, query, update, upsert=False):
    """
    Mongo does not see replace w/ upsert as an atomic action:
    https://jira.mongodb.org/browse/SERVER-14322

    This function will try a replace_one operation, returning the result and if the operation succeeded.
    """
    try:
        result = db[coll_name].update_one(query, update, upsert=upsert)
    except DuplicateKeyError:
        return result, False
    else:
        return result, True
