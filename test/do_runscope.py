import json

import ramlfications
import runscope

api = ramlfications.parse("../raml/api.raml")
print(json.dumps(runscope.get_api_runscope_test(api), indent=4))
