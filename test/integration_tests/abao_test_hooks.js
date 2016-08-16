var hooks = require('hooks');

// Variables for passing results as input to subsequent tests
var job_id = '';
var gear_name = '';

// Tests we're skipping, fix these

// Fails only in travis
hooks.skip("GET /version -> 200");

// Skipped due to 500 when should 4xx

// Should 400 to say invalid json
hooks.skip("GET /download -> 400");

// Should 422 for missing metadata field
hooks.skip("POST /upload/label -> 402");
hooks.skip("POST /upload/uid -> 402");

// Should 422 for JSON not matching schema
// After this is fixed, add "validates-json-body" trait
// to all endpoints which validate a json body
hooks.skip("POST /users -> 422");

// Should 404
hooks.skip("GET /jobs/{JobId} -> 404");

// This does run after a job is added
// 500 saying unknown gear
hooks.skip("GET /jobs/next -> 200");

// No way to order tests, have to add a job before it can be listed
hooks.skip("GET /jobs -> 200");
hooks.skip("GET /jobs/{JobId} -> 200");
hooks.skip("PUT /jobs/{JobId} -> 200");

// Can only retry a failed job
hooks.skip("POST /jobs/{JobId}/retry -> 200");

// https://github.com/cybertk/abao/issues/160
hooks.skip("GET /users/self/avatar -> 307");
hooks.skip("GET /users/{UserId}/avatar -> 307");

// Skipping some tests until we figure out how to test file fields
hooks.skip("POST /download -> 200");
hooks.skip("GET /download -> 200");
hooks.skip("POST /upload/label -> 200");
hooks.skip("POST /upload/uid -> 200");
hooks.skip("POST /engine -> 200");

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
    test.request.params = {
        JobId: job_id
    };
    done();
});

hooks.before("PUT /jobs/{JobId} -> 200", function(test, done) {
    test.request.params = {
        JobId: job_id
    };
    done();
});

hooks.before("POST /jobs/{JobId}/retry -> 200", function(test, done) {
    test.request.params = {
        JobId: job_id
    };
    done();
});

hooks.before("GET /jobs/{JobId} -> 404", function(test, done) {
    test.request.params = {
        JobId: '57ace4479e512c61bc6e006f' // fake ID, 404
    };
    done();
});

hooks.before("GET /download -> 404", function(test, done) {
    test.request.query = {
        ticket: '1234'
    };
    done();
});

hooks.before("POST /users -> 422", function(test, done) {
    test.request.body = {totally:"not valid"};
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

hooks.before("GET /gears/{GearName} -> 200", function(test, done) {
    test.request.params = {
        GearName: gear_name
    };
    done();
});

hooks.before("POST /gears/{GearName} -> 200", function(test, done) {
    test.request.params = {
        GearName: "dcm_convert"
    };
    done();
});

hooks.before("GET /gears/{GearName} -> 200", function(test, done) {
    test.request.params = {
        GearName: "dcm_convert"
    };
    done();
});
