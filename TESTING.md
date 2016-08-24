## Run the tests
### OSX
```
./test/bin/run-tests-osx.sh
```

### Ubuntu
```
# Follow installation instructions in README first
workon scitran-core
export env
./test/bin/setup-integration-tests-ubuntu.sh
./test/bin/run-tests-ubuntu.sh
```

### Tools
- [abao](https://github.com/cybertk/abao/)
- [postman](https://www.getpostman.com/docs/)

### Testing API against RAML with Abao
Abao is one of the testing tools run during our TravisCI build.  It tests the API implementation against what’s defined in the RAML spec.  Adding a new resource / url to the RAML spec will cause Abao to verify that resource during integration tests.  Sometimes abao cannot properly test a resource (file field uploads) or a test may require chaining variable.  Abao has before and after hooks for tests, written in javascript.  These can be used to skip a test, inject variables into the request, or make extra assertions about the response.  See tests/integration/abao in the repo for the hooks file.  See [abao github readme](https://github.com/cybertk/abao/blob/master/README.md) for more information on how to use hooks.



### Integration Testing with Postman
1. Open postman and import “core/tests/integration_tests/postman/integration_tests.postman_collection”
2. Also import and activate “core/tests/integration_tests/postman/environments/local_scitran_core.postman_environment”  if you have not done so previously
3. Optionally, import raml folder from API into a separate collection, so you can copy requests for testing
4. Add a new request to the postman collection for each request you’d like to test.  See links below for documentation on adding requests and javascript snippets for test assertions.  When you define your requests, make sure to use the {{baseUri}} and {{test_user}} variables, do not hardcode these values
5. Start the API and load integration test config
6. In postman, on the collection object, click the “>” symbol to expand some actions and then click “Run”.  Verify results.
7. On the collection object click “...” to expand some actions and then export the collection
8. Save the updated collection of tests to “core/tests/integration_tests/postman/integration_tests.postman_collection”

Postman Links

- https://www.getpostman.com/docs/
- https://www.getpostman.com/docs/writing_tests
- https://www.getpostman.com/docs/testing_examples
- http://blog.getpostman.com/2014/03/07/writing-automated-tests-for-apis-using-postman/
- https://www.getpostman.com/docs/environments
- https://www.getpostman.com/docs/newman_intro
