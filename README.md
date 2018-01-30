[![Build Status](https://travis-ci.org/scitran/core.svg?branch=master)](https://travis-ci.org/scitran/core)
[![Coverage Status](https://codecov.io/gh/scitran/core/branch/master/graph/badge.svg)](https://codecov.io/gh/scitran/core/branch/master)
[![Code Climate](https://codeclimate.com/github/scitran/core/badges/gpa.svg)](https://codeclimate.com/github/scitran/core)

# SciTran – Scientific Transparency

### Overview

SciTran Core is a RESTful HTTP API, written in Python and backed by MongoDB. It is the central component of the [SciTran data management system](https://scitran.github.io). Its purpose is to enable scientific transparency through secure data management and reproducible processing.


### [Documentation](https://scitran.github.io/core)

### [Contributing](https://github.com/scitran/core/blob/master/CONTRIBUTING.md)

### [Testing](https://github.com/scitran/core/blob/master/TESTING.md)

### [License](https://github.com/scitran/core/blob/master/LICENSE)


### Usage
```
docker run -p 80:80 -e SCITRAN_CORE_DRONE_SECRET=secret scitran/core
```
