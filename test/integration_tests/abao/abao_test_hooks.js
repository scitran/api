var hooks = require('hooks');
var chai = require("chai");
var assert = chai.assert;

// Variables for passing results as input to subsequent tests
var job_id = '';
var gear_name = 'test-case-gear';
var group_id = 'test_group';
var collection_id = '';
var delete_collection_id = '';
var test_session_1 = null;
var test_session_2_id = null;
var test_acquisition_1 = null;
var test_project_1 = null;

// Tests we're skipping, fix these

// Fails only in travis
hooks.skip("GET /version -> 200");

// Should 400 to say invalid json
hooks.skip("GET /download -> 400");

// Should 422 for missing metadata field
hooks.skip("POST /upload/label -> 402");
hooks.skip("POST /upload/uid -> 402");
hooks.skip("POST /upload/uid-match -> 402");

// Should 404
hooks.skip("GET /jobs/{JobId} -> 404");

// Can only retry a failed job
hooks.skip("POST /jobs/{JobId}/retry -> 200");

// https://github.com/cybertk/abao/issues/160
hooks.skip("GET /users/self/avatar -> 307");
hooks.skip("GET /users/{UserId}/avatar -> 307");

// Tests that are skipped because we do them in postman or python

// Skipping because abao doesn't support file fields
hooks.skip("POST /download -> 200");
hooks.skip("GET /download -> 200");
hooks.skip("POST /upload/label -> 200");
hooks.skip("POST /upload/uid -> 200");
hooks.skip("POST /upload/uid-match -> 200");
hooks.skip("POST /upload/uid-match -> 404");
hooks.skip("POST /engine -> 200");

hooks.beforeEach(function (test, done) {
    test.request.query.root = "true"
    test.request.headers.Authorization = "scitran-user XZpXI40Uk85eozjQkU1zHJ6yZHpix+j0mo1TMeGZ4dPzIqVPVGPmyfeK";
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

hooks.before("GET /jobs/{JobId}/config.json -> 200", function(test, done) {
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

hooks.before("POST /users -> 400", function(test, done) {
    test.request.body = {api_key:{key:"test"}};
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

hooks.before("PUT /users/{UserId} -> 400", function(test, done) {
    test.request.params = {
        UserId: "jane.doe@gmail.com"
    };
    test.request.body = {"not_a_valid_property":"foo"};
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
        GearName: gear_name
    };
    done();
});

hooks.before("GET /gears/{GearName} -> 200", function(test, done) {
    test.request.params = {
        GearName: gear_name
    };
    done();
});

hooks.before("GET /groups -> 200", function(test, done) {
    // POST happens after GET, so hardcode a group_id
    // group_id = test.response.body[0]._id;
    done();
});

hooks.before("PUT /groups/{GroupId} -> 400", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    test.request.body = {"not_a_real_property":"foo"};
    done();
});

hooks.before("POST /groups -> 400", function(test, done) {
    test.request.body = {"not_a_real_property":"foo"};
    done();
});


hooks.before("GET /groups/{GroupId} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    done();
});



hooks.before("DELETE /groups/{GroupId} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    done();
});

hooks.after("GET /collections -> 200", function(test, done) {
    collection_id = test.response.body[0]._id;
    delete_collection_id = test.response.body[1]._id;
    done();
});

hooks.before("GET /collections/{CollectionId} -> 200", function(test, done) {
    test.request.params.CollectionId = collection_id;
    done();
});

hooks.before("GET /collections/{CollectionId}/sessions -> 200", function(test, done) {
    test.request.params.CollectionId = collection_id;
    done();
});

hooks.before("GET /collections/{CollectionId}/acquisitions -> 200", function(test, done) {
    test.request.params.CollectionId = collection_id;
    done();
});

hooks.before("POST /collections -> 400", function(test, done) {
    test.request.params.CollectionId = collection_id;
    test.request.body.foo = "not an allowed property";
    done();
});

hooks.before("PUT /collections/{CollectionId} -> 400", function(test, done) {
    test.request.params.CollectionId = collection_id;
    test.request.body.foo = "not an allowed property";
    done();
});

hooks.before("DELETE /collections/{CollectionId} -> 200", function(test, done) {
    test.request.params.CollectionId = delete_collection_id;
    done();
});

hooks.after("GET /sessions -> 200", function(test, done) {
    test_session_1 = test.response.body[0];
    assert.equal(test_session_1.label, "test-session-1");
    done();
});

hooks.before("GET /sessions/{SessionId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    done();
});

hooks.before("POST /sessions -> 200", function(test, done) {
    test.request.body.project = test_session_1.project;
    done();
});

hooks.after("POST /sessions -> 200", function(test, done) {
    test_session_2_id = test.response.body._id
    done();
});


hooks.before("POST /sessions -> 400", function(test, done) {
    test.request.body.foo = "not an allowed property";
    test.request.body.project = test_session_1.project;
    done();
});

hooks.before("PUT /sessions/{SessionId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.body = {
        project: test_session_1.project,
        label: "new-label-test-session-1"
    };
    done();
});

hooks.before("PUT /sessions/{SessionId} -> 400", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.body = {
        project: test_session_1.project,
        "not_a_real_property": "new-label-test-session-1"
    };
    done();
});

hooks.before("DELETE /sessions/{SessionId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_2_id;
    done();
});


hooks.before("GET /sessions/{SessionId}/jobs -> 200", function(test, done) {
  test.request.params.SessionId = test_session_1._id;
  done();
});

hooks.after("GET /acquisitions -> 200", function(test, done) {
    test_acquisition_1 = test.response.body[0];
    assert.equal(test_acquisition_1.label, "test-acquisition-1");
    example_acquisition = test.response.body[1];
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId} -> 200", function(test, done) {
    test.request.params.AcquisitionId = test_acquisition_1._id;
    done();
});

hooks.before("POST /acquisitions -> 200", function(test, done) {
    test.request.body.session = test_session_1._id;
    done();
});

hooks.before("POST /acquisitions -> 400", function(test, done) {
    test.request.body.session = test_session_1._id;
    test.request.body.foo = "bar";
    done();
});

hooks.before("PUT /acquisitions/{AcquisitionId} -> 200", function(test, done) {
    test.request.params.AcquisitionId = test_acquisition_1._id;
    test.request.body = {"label":"test-acquisition-1-new-label"};
    done();
});


hooks.before("PUT /acquisitions/{AcquisitionId} -> 400", function(test, done) {
    test.request.params.AcquisitionId = test_acquisition_1._id;
    test.request.body = {"not-real":"an invalid property"};
    done();
});

hooks.before("DELETE /acquisitions/{AcquisitionId} -> 200", function(test, done) {
    test.request.params.AcquisitionId = example_acquisition._id;
    done();
});

hooks.after("GET /projects -> 200", function(test, done) {
    test_project_1 = test.response.body[0];
    assert.equal(test_project_1.label, "test-project");
    done();
});

hooks.before("POST /projects -> 400", function(test, done) {
    test.request.body.not_real = "an invalid property";
    done();
});

hooks.before("GET /projects/{ProjectId} -> 200", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    done();
});

hooks.before("PUT /projects/{ProjectId} -> 400", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    test.request.body = {"not_real":"fake property"};
    done();
});
