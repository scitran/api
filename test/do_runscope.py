import ramlfications
import runscope

api = ramlfications.parse("../raml/api.raml")
print(runscope.get_api_test_steps(api))
