# vim: filetype=python
import sys
import os.path

repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
sys.path.append(repo_path)

from api import api

application = api.app_factory()
