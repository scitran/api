[![Build Status](https://travis-ci.org/scitran/core.svg?branch=master)](https://travis-ci.org/scitran/core)
[![Coverage Status](https://codecov.io/gh/scitran/core/branch/master/graph/badge.svg)](https://codecov.io/gh/scitran/core/branch/master)
[![Code Climate](https://codeclimate.com/github/scitran/core/badges/gpa.svg)](https://codeclimate.com/github/scitran/core)

#### Flywheel has been the primary contributor to this repository for quite some time. We have now decided to fork scitran/core into [flywheel-io/core](https://github.com/flywheel-io/core), where we are planning to maintain and develop the code as open source, under the existing MIT license. All open issues in this repo have been closed, and corresponding issues have been opened in flywheel-io/core.

# SciTran – Scientific Transparency

### Overview

SciTran Core is a RESTful HTTP API, written in Python and backed by MongoDB. It is the central component of the [SciTran data management system](https://scitran.github.io). Its purpose is to enable scientific transparency through secure data management and reproducible processing.


### [Documentation](https://scitran.github.io/core)

API documentation for branches and tags can be found at `https://scitran.github.io/core/branches/<branchname>` and
`https://scitran.github.io/core/tags/<tagname>`.

### [Contributing](https://github.com/scitran/core/blob/master/CONTRIBUTING.md)

### [Testing](https://github.com/scitran/core/blob/master/tests/README.md)

### [License](https://github.com/scitran/core/blob/master/LICENSE)


### Usage
**Currently Python 2 Only**

#### OSX
```
$ ./bin/run-dev-osx.sh --help
```

For the best experience, please upgrade to a recent version of bash.
```
brew install bash bash-completion
sudo dscl . -create /Users/$(whoami) UserShell /usr/local/bin/bash
```

#### Ubuntu
```
mkvirtualenv scitran-core
./bin/install-ubuntu.sh
uwsgi --http :8080 --master --wsgi-file bin/api.wsgi -H $VIRTUAL_ENV \
    --env SCITRAN_PERSISTENT_DB_URI="mongodb://localhost:27017/scitran-core"
```
