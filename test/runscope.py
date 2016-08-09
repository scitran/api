import json
import warnings

class APISystemTest:
    """A base class for system tests

    Must have an attribute called "path",
    which is used to match the test case to an endpoint
    """
    path = None

    def __init__(self, *args, **kwargs):
        """
        Reserved for future use
        """
        pass

    def test_get(self, resource):
        """Creates runscope test steps for HTTP GET

        :param resource: The resource to generate tests for
        :type resource: :class:`ramlfications.raml.ResourceNode`

        :returns: list -- A list of runscope test dictionary.
            Each test dictionary may contain the following keys:
            queryParameters: A dictionary of query parameters
            headers: A dictionary of hearders
            body: Content of request body (N/A for GET method)
            form: Form data to send in place of body
            assertions:  A list of test assertions
            variables: Pass results as input to other steps
            See https://www.runscope.com/docs/api/steps#add-request
        """
        return []

    def test_post(self, resource):
        """Same as :meth:`test_get` except for HTTP POST"""
        return []

    def test_put(self, resource):
        """Same as :meth:`test_get` except for HTTP POST"""
        return []

    def test_get_example(self, resource):
        response = resource.responses[0]
        response_body = response.body[0]
        assertions = self.get_response_body_assertions(response)
        assertions.append(
            {
                "source":"response_status",
                "comparison":"equal",
                "value":response.code
            }
        )
        return [
            {
              "queryParameters":{},
              "variables": [],
              "headers":{},
              "assertions": assertions
            }
        ]

    def test_post_example(self, resource):
        """Creates test steps based on the resource example"""
        body = resource.body[0]
        form_data = {}
        if body.form_params:
            for form_param in body.form_params:
                form_data[form_param.name] = form_param.example
        response = resource.responses[0]
        assertions = self.get_response_body_assertions(response)
        assertions.append(
            {
                "source":"response_status",
                "comparison":"equal",
                "value":response.code
            }
        )
        return [
            {
              "queryParameters":{},
              "body": json.dumps(body.example),
              "form": form_data,
              "variables": [],
              "headers": {
                "Content-Type":body.mime_type
              },
              "assertions": assertions
            }
        ]

    def get_response_body_assertions(self, response):
        response_body = response.body[0]
        if not response_body.example:
            raise ValueError(
                "Response body contains no example: {0}".format(response.raw)
                )
        assertions = []
        if isinstance(response_body.example, dict):
            for response_key, response_value in response_body.example.items():
                assertions.append(
                    {
                        "source":"response_json",
                        "comparison":"equal",
                        "property":response_key,
                        "value":response_value
                    }
                )
        else:
            assertions.append(
                {
                    "source":"response_text",
                    "comparison":"equal",
                    "value":json.dumps(response_body.example)
                }
            )
        return assertions

class UsersCollectionTest(APISystemTest):
    path = "/api/users"

system_test_classes = [UsersCollectionTest]

def format_resources_by_path(resources):
    raml_resources = {}
    for resource in resources:
        path = resource.path
        if path not in raml_resources:
            raml_resources[path] = {}
        raml_resources[path][resource.method] = resource
    return raml_resources

def get_api_test_steps(raml_api):
    raml_resources = format_resources_by_path(raml_api.resources)
    untested_endpoints = [] # Used to check if all endpoints have tests
    for path, resource_methods in raml_resources.items():
        for method, resource in resource_methods.items():
            untested_endpoints.append((path, method))
    all_steps = []
    for test_class in system_test_classes:
        resources_by_method = raml_resources[test_class.path]
        system_test = test_class()
        methods = ["post", "get", "put"]
        for method, resource in resources_by_method.items():
            example_test_name = "test_{0}_example".format(method)
            example_test_method = getattr(system_test, example_test_name)
            all_steps += example_test_method(resource)
            test_name = "test_{0}".format(method)
            test_method = getattr(system_test, test_name)
            all_steps += test_method(resource)
            untested_endpoints.remove((test_class.path, method))
    if untested_endpoints:
        warnings.warn("Untested endpoints:  {0}".format(untested_endpoints))
    return all_steps
