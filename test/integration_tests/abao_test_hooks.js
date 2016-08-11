var hooks = require('hooks');

# Variables for passing results as input to subsequent tests
var job_id = '';
var gear_name = '';

hooks.beforeEach(function (test, done) {
    test.request.query = {
      user: 'admin@user.com',
      root: 'true'
    };
    done();
});

hooks.after("GET /jobs -> 200", function(test, done) {
    job_id = test.response.body[0]._id;
    done();
});

hooks.before("GET /jobs/{JobId} -> 200", function(test, done) {
    console.log(job_id);
    test.request.params = {
        JobId: job_id
    };
    done();
});

hooks.before("PUT /jobs/{JobId} -> 200", function(test, done) {
    console.log(job_id);
    test.request.params = {
        JobId: job_id
    };
    done();
});

hooks.before("POST /jobs/{JobId}/retry -> 200", function(test, done) {
    console.log(job_id);
    test.request.params = {
        JobId: job_id
    };
    done();
});

hooks.before("GET /jobs/{JobId} -> 404", function(test, done) {
    console.log(job_id);
    test.request.params = {
        JobId: '57ace4479e512c61bc6e006f' # fake ID, 404
    };
    done();
});

hooks.before("GET /download -> 404", function(test, done) {
    test.request.query = {
        ticket: '1234'
    };
    done();
});

hooks.before("GET /users/{UserId} -> 200", function(test, done) {
    test.request.params = {
        UserId: "jane.doe@gmail.com"
    };
    done();
});

hooks.before("PUT /users/{UserId} -> 200", function(test, done) {
    test.request.params = {
        UserId: "jane.doe@gmail.com"
    };
    done();
});

hooks.before("DELETE /users/{UserId} -> 200", function(test, done) {
    test.request.params = {
        UserId: "jane.doe@gmail.com"
    };
    done();
});

hooks.after("GET /gears -> 200", function(test, done) {
    gear_name = test.response.body[0].name
    done();
});

hooks.before("GET /gears/{GearName} -> 200", function(test, done) {
    test.request.params = {
        GearName: gear_name;
    };
});

hooks.before("POST /gears/{GearName} -> 200", function(test, done) {
    test.request.params = {
        GearName: gear_name;
    };
});


hooks.skip("GET /users/self/avatar -> 307"); // https://github.com/cybertk/abao/issues/160
hooks.skip("GET /users/{UserId}/avatar -> 307"); // https://github.com/cybertk/abao/issues/160

# Skipping some tests until we figure out how to test file fields
hooks.skip("POST /download -> 200");
hooks.skip("GET /download -> 200");
hooks.skip("POST /upload/label -> 200");
hooks.skip("POST /upload/uid -> 200");
hooks.skip("POST /engine -> 200");


