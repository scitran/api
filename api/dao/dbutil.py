import random
import time

from pymongo.errors import DuplicateKeyError
from .. import config
from . import APIStorageException




def fault_tolerant_replace_one(coll_name, query, update, upsert=False):
    """
    Mongo does not see replace w/ upsert as an atomic action:
    https://jira.mongodb.org/browse/SERVER-14322

    Attempt a retry if first try produces DuplicateKeyError
    """

    attempts = 0
    while attempts < 10:
        attempts += 1
        try:
            result = config.db[coll_name].replace_one(query, update, upsert=upsert)
        except DuplicateKeyError: # cover 100
            time.sleep(random.uniform(0.01,0.05))
        else:
            return result

    raise APIStorageException('Unable to replace object.') # cover 100
