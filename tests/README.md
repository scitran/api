## Testing
Build scitran-core and run automated tests in a docker container:
```
./tests/bin/docker-tests.sh
```

* To skip building the image, use `--no-build` (`-B`)
* All tests (unit, integration and linting) are executed by default
* To pass any arguments to `py.test`, use `-- PYTEST_ARGS`
    * To run only a subset of test, use the [keyword expression filter](https://docs.pytest.org/en/latest/usage.html#specifying-tests-selecting-tests) `-k`
    * To see `print` output during tests, increase verbosity with `-vvv`
    * To get a debugger session on failures, use [`--pdb`](https://docs.pytest.org/en/latest/usage.html#dropping-to-pdb-python-debugger-on-failures)

See [py.test usage](https://docs.pytest.org/en/latest/usage.html) for more.

### Example
The most common use case is adding a new (still failing) test, and wanting to
* (re-)run it as fast as possible (`-B` and `-k foo`)
* see output from quick and dirty `print` statements in the test (`-vvv`)
* get into an interactive pdb session to inspect what went wrong (`--pdb`)

```
./tests/bin/docker-tests.sh -B -- -k foo -vvv --pdb
```
