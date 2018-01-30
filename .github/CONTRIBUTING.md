## Contributing
1. Contributions should follow the "Code Standards" section of this document.
1. If adding an endpoint or resource to the API, also follow "Adding an API Resource".
1. Follow commit message guidelines.
1. Use `git rebase [-i]` to clean up your contribution and resolve pending merge conflicts.
1. Submit a pull request and ensure that CI passes.


## Upgrading Python Packages

List outdated packages
```
pip list --local --outdated
```

Then review and decide what upgrades to make, if any.
Changes to `requirements.txt` should always be by pull request.

## Code Standards

### Testing
- Add tests for every change made
- Tests should be realistic and exercise a wide range of possibilities

### Docstrings
- Use [Google Style Docstrings](http://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html).
- Add docstrings to all functions with a one-line description of its purpose.

### Format
Ensure that `./tests/bin/run-tests-docker.sh -- -l` exits without errors.

### Commit Messages
1. The subject line should be a phrase describing the commit and limited to 50 characters
1. The subject line should be as specific as possible, e.g. "Add new API resource for user API keys", rather than "Update authentication".

## Adding an API Resource
### Design Resource
1. Write a description of your API resource and its business functionality.
1. Choose a descriptive name for your resource that aligns with existing names.
1. Create a URL from the name. If your resource is a collection, the name should be a pluralized noun, e.g., "files".

### Quality Standards
1. All API resources must have input validation
1. New API resources should follow the error handling convention and raise webapp2.HTTPException

### Add RAML for API Endpoints
1. Create a new resource file, called `<resource_name>.raml`, e.g., `files.raml`. Create this file in the `raml/resources` directory.
1. In `api.raml`, add a line with the URL of your resource and an include directive for your resource raml file, e.g., `/files: !include resources/files.raml`.
1. In your resource file, define your resource. Begin by adding a `description` property with the description you wrote in step 1.
1. Add example properties for both request and response. Examples should be stored in the `examples/` directory, e.g., `raml/examples/request/files.json`.
1. Use [JSONSchema.net](http://jsonschema.net/) to generate a JSON schema for both request and response body. Edit the schema as necessary. Before generating your schema, scroll down and uncheck "allow additional properties".  Schemas are stored in the `schemas/` directory, e.g., `raml/schemas/input/files.json`.
1. Verify that the example properties pass schema validation by running the unit tests. New schemas and examples will be tested automatically. (See testing instructions below)

### Testing
Follow the procedures outlined in our [testing instructions](https://github.com/scitran/core/blob/master/TESTING.md).
