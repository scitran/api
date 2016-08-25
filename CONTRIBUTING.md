## Contributing
1. Contributions should follow the "Code Standards" section of this document.
1. If adding an endpoint or resource to the API, also follow "Adding an API Resource".
1. Follow commit message guidelines.
1. Use `git rebase [-i]` to clean up your contribution and resolve pending merge conflicts.
1. Submit a pull request and ensure that CI passes.


## Code Standards
### Docstrings
- Use [Google Style Docstrings](http://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html).
- Add docstrings to all functions with a one-line description of its purpose.

### Format
- Ensure that `./test/lint.sh api` exits without errors.

### Commit Messages
1. First line should be a phrase describing the commit, do not use punctuation
1. Make sure the subject line is capitalized and no longer than 50 characters
1. Always use present tense / imperative mood  e.g. "Fix bug in foo.py", NOT "fixed" or "fixes"
1. Blank line, followed by a detailed description (optional)  Use punctuation
1. When writing your description line length should be 72 characters at most
1. Description should be broken up into paragraphs no more than 4 sentences.
1. Make sure your description says what you changed and why, less important is how.
1. Blank line, followed by "Resolves: #xxx, #yyy" for any issues fixed by the commit
1. Follow immediately with a line containing "See also: #xxx, #yyy" for any other issues
1. These steps were adapted from [7 Rules of a Great Commit Message](http://chris.beams.io/posts/git-commit/#seven-rules).  Visit for more info

## Adding an API Resource
### Design Resource
1. Write a description of your API resource and its business functionality.
1. Choose a descriptive name for your resource that aligns with existing names.
1. Create a URL from the name. If your resource is a collection, the name should be a pluralized noun, e.g., "files".

### Add RAML for API Endpoints
1. Create a new resource file, called `<resource_name>.raml`, e.g., `files.raml`. Create this file in the `raml/resources` directory.
1. In `api.raml`, add a line with the URL of your resource and an include directive for your resource raml file, e.g., `/files: !include resources/files.raml`.
1. In your resource file, define your resource. Begin by adding a `description` property with the description you wrote in step 1.
1. Add example properties for both request and response. Examples should be stored in the `examples/` directory, e.g., `raml/examples/request/files.json`.
1. Use [JSONSchema.net](http://jsonschema.net/) to generate a JSON schema for both request and response body. Edit the schema as necessary. Before generating your schema, scroll down and uncheck "allow additional properties".  Schemas are stored in the `schemas/` directory, e.g., `raml/schemas/input/files.json`.

### Testing
Follow the procedures outlined in our [testing instructions](https://github.com/scitran/core/blob/master/TESTING.md).
