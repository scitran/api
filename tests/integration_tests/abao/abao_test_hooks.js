var hooks = require('hooks');
var chai = require('chai');
var assert = chai.assert;

// Variables for passing results as input to subsequent tests
var gear_name = 'test-case-gear';
var group_id = 'test-group';
var delete_group_id = 'example_group';
var test_group_tag = 'test-group-tag';
var collection_id = 'test-collection-1';
var delete_collection_id = '';
var test_collection_1 = null;
var test_collection_tag = 'test-collection-tag';
var test_session_1 = null;
var test_session_2_id = null;
var test_session_tag = 'test-session-tag';
var test_session_1_analysis_2_id = null;
var test_acquisition_1 = null;
var test_acquisition_tag = 'test-acq-tag';
var example_acquisition_id = '';
var test_project_1 = null;
var test_project_tag = 'test-project-tag';
var delete_project_id = '';
var device_id = 'bootstrapper_Bootstrapper';
var injected_api_key = 'XZpXI40Uk85eozjQkU1zHJ6yZHpix+j0mo1TMeGZ4dPzIqVPVGPmyfeK';
var search_id = '';
var delete_search_id = '';
var user_id = 'user@user.com'

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

// Cannot get JobId without GET /jobs endpoint
hooks.skip("GET /jobs/{JobId} -> 200");
hooks.skip("GET /jobs/{JobId}/config.json -> 200");
hooks.skip("POST /jobs/{JobId}/retry -> 200");
hooks.skip("GET /jobs/{JobId} -> 404");

// https://github.com/cybertk/abao/issues/160
hooks.skip("GET /users/self/avatar -> 307");
hooks.skip("GET /users/{UserId}/avatar -> 307");

// drones currently use shared secret, allow when using API keys
hooks.skip("POST /devices -> 200")
hooks.skip("GET /devices/self -> 200")

// Tests that are skipped because we do them in python

// Skipping because abao doesn't support file fields
hooks.skip("POST /download -> 200");
hooks.skip("GET /download -> 200");
hooks.skip("POST /upload/label -> 200");
hooks.skip("POST /upload/uid -> 200");
hooks.skip("POST /upload/uid-match -> 200");
hooks.skip("POST /upload/uid-match -> 404");
hooks.skip("POST /engine -> 200");
hooks.skip("POST /collections/{CollectionId}/packfile-start -> 200");
hooks.skip("POST /collections/{CollectionId}/packfile -> 200");
hooks.skip("GET /collections/{CollectionId}/packfile-end -> 200");
hooks.skip("POST /sessions/{SessionId}/packfile-start -> 200");
hooks.skip("POST /sessions/{SessionId}/packfile -> 200");
hooks.skip("GET /sessions/{SessionId}/packfile-end -> 200");
hooks.skip("POST /acquisitions/{AcquisitionId}/packfile-start -> 200");
hooks.skip("POST /acquisitions/{AcquisitionId}/packfile -> 200");
hooks.skip("GET /acquisitions/{AcquisitionId}/packfile-end -> 200");
hooks.skip("POST /projects/{ProjectId}/packfile-start -> 200");
hooks.skip("POST /projects/{ProjectId}/packfile -> 200");
hooks.skip("GET /projects/{ProjectId}/packfile-end -> 200");


// Skipping until merge with rest of project raml (So we have a ProjectId)
hooks.skip("POST /projects/{ProjectId}/template -> 200")
hooks.skip("DELETE /projects/{ProjectId}/template -> 200")
hooks.skip("POST /projects/{ProjectId}/recalc -> 200")
hooks.skip("GET /projects/{ProjectId}/rules -> 200")

// Porting to python as per #600
hooks.skip("POST /jobs/add -> 200")
hooks.skip("PUT /jobs/{JobId} -> 200")
hooks.skip("GET /gears/{GearId} -> 200")
hooks.skip("GET /sessions/{SessionId}/jobs -> 200")

// Cannot be ran due to gear IDs being used as per #
hooks.skip("POST /sessions/{SessionId}/analyses -> 200")
hooks.skip("GET /sessions/{SessionId}/analyses/{AnalysisId} -> 200")
hooks.skip("DELETE /sessions/{SessionId}/analyses/{AnalysisId} -> 200")
// Related, ref #696
hooks.skip("DELETE /gears/{GearId} -> 200")


hooks.before("POST /login -> 200", function(test, done) {
    test.request.body = {
        'code': injected_api_key,
        'auth_type': 'api-key'
    };
    done();
});

hooks.beforeEach(function (test, done) {
    test.request.query.root = "true"
    test.request.headers.Authorization = "scitran-user XZpXI40Uk85eozjQkU1zHJ6yZHpix+j0mo1TMeGZ4dPzIqVPVGPmyfeK";
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

hooks.before("GET /users/{UserId}/acquisitions -> 200", function(test, done) {
    test.request.params = {
        UserId: "admin@user.com"
    };
    done();
});

hooks.before("GET /users/{UserId}/collections -> 200", function(test, done) {
    test.request.params = {
        UserId: "admin@user.com"
    };
    done();
});

hooks.before("GET /users/{UserId}/projects -> 200", function(test, done) {
    test.request.params = {
        UserId: "admin@user.com"
    };
    done();
});

hooks.before("GET /users/{UserId}/sessions -> 200", function(test, done) {
    test.request.params = {
        UserId: "admin@user.com"
    };
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
        GroupId: delete_group_id
    };
    done();
});

hooks.before("POST /groups/{GroupId}/permissions -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    test.request.body = {
        _id: "test@user.com",
        access: "ro"
    }
    done();
});

hooks.before("POST /groups/{GroupId}/permissions -> 400", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    test.request.body.foo = "bar";
    done();
});

hooks.before("GET /groups/{GroupId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        UserId: "test@user.com"
    };
    done();
});

hooks.before("PUT /groups/{GroupId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        UserId: "test@user.com"
    };
    test.request.body = {
        _id: "test@user.com",
        access: "admin"
    };
    done();
});

hooks.before("PUT /groups/{GroupId}/permissions/{UserId} -> 400", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        UserId:"test@user.com"
    };
    test.request.body = {
        _id: "test@user.com",
        access: "rw",
        not_a_real_property: "foo"
    };
    done();
});

hooks.before("DELETE /groups/{GroupId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        UserId: "test@user.com"
    };
    done();
});

hooks.before("POST /groups/{GroupId}/tags -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    test.request.body = {
        "value":test_group_tag
    };
    done();
});

hooks.before("POST /groups/{GroupId}/tags -> 400", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    test.request.body = {
        "value":test_group_tag,
        "bad property": "foo"
    };
    done();
});

hooks.before("GET /groups/{GroupId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        TagValue: test_group_tag
    };
    done();
});

hooks.before("PUT /groups/{GroupId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        TagValue: test_group_tag
    };
    test_group_tag = "a-new-tag";
    test.request.body = {
        "value":test_group_tag
    };
    done();
});

hooks.before("PUT /groups/{GroupId}/tags/{TagValue} -> 400", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        TagValue: test_group_tag
    };
    test.request.body = {
        "value":test_group_tag,
        "bad proeprty":"blah"
    };
    done();
});

hooks.before("DELETE /groups/{GroupId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id,
        TagValue: test_group_tag
    };
    done();
});

hooks.before("GET /groups/{GroupId}/projects -> 200", function(test, done) {
    test.request.params = {
        GroupId: group_id
    };
    done();
});


// set initial test_collection_1
hooks.after("GET /collections -> 200", function(test, done) {
    test_collection_1 = test.response.body[0];
    collection_id = test.response.body[0]._id;
    delete_collection_id = test.response.body[1]._id;
    done();
});

hooks.before("GET /collections/{CollectionId} -> 200", function(test, done) {
    test.request.params.CollectionId = collection_id;
    done();
});

// set detailed test_collection_1 (including analyses, that are omitted during listing)
hooks.after("GET /collections/{CollectionId} -> 200", function(test, done) {
    test_collection_1 = test.response.body;
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

hooks.before("POST /collections/{CollectionId}/tags -> 200", function(test, done) {
    test.request.params.CollectionId = collection_id;
    test.request.body = {
        "value":test_collection_tag
    };
    done();
});

hooks.before("POST /collections/{CollectionId}/tags -> 400", function(test, done) {
    test.request.params.CollectionId = collection_id;
    test.request.body = {
        "value":""
    };
    done();
});

hooks.before("GET /collections/{CollectionId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        TagValue : test_collection_tag
    };
    done();
});

hooks.before("PUT /collections/{CollectionId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        TagValue : test_collection_tag
    };
    test_collection_tag = "new-tag-value";
    test.request.body = {
        "value":test_collection_tag
    };
    done();
});

hooks.before("PUT /collections/{CollectionId}/tags/{TagValue} -> 400", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        TagValue : test_collection_tag
    };
    test.request.body = {
        "value":""
    };
    done();
});

hooks.before("DELETE /collections/{CollectionId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        TagValue : test_collection_tag
    };
    done();
});

hooks.before("GET /collections/{CollectionId}/files/{FileName} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        FileName : "notes.txt"
    };
    test.request.query = {
        "ticket":""
    };
    done();
});

hooks.before("POST /collections/{CollectionId}/permissions -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id
    };
    test.request.body = {
        "_id":"test@user.com",
        "access":"ro"
    };
    done();
});

hooks.before("POST /collections/{CollectionId}/permissions -> 400", function(test, done) {
    test.request.params = {
        CollectionId : collection_id
    };
    test.request.body = {
        "not a valid":"permissions entry"
    };
    done();
});

hooks.before("GET /collections/{CollectionId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        UserId: "test@user.com"
    };
    done();
});

hooks.before("PUT /collections/{CollectionId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        UserId: "test@user.com"
    };
    test.request.body = {
        "access":"rw",
        "_id":"test@user.com"
    };
    done();
});

hooks.before("PUT /collections/{CollectionId}/permissions/{UserId} -> 400", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        UserId: "test@user.com"
    };
    test.request.body = {
        "not a valid":"permissions entry"
    };
    done();
});

hooks.before("DELETE /collections/{CollectionId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        UserId: "test@user.com"
    };
    done();
});

hooks.before("POST /collections/{CollectionId}/notes -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id
    };
    done();
});

hooks.before("POST /collections/{CollectionId}/notes -> 400", function(test, done) {
    test.request.params = {
        CollectionId : collection_id
    };
    test.request.body = {
        "not real":"property"
    };
    done();
});

hooks.before("GET /collections/{CollectionId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        NoteId: test_collection_1.notes[0]._id
    };
    done();
});

hooks.before("PUT /collections/{CollectionId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        NoteId: test_collection_1.notes[0]._id
    };
    test.request.body = {
        "text":"new note"
    };
    done();
});

hooks.before("PUT /collections/{CollectionId}/notes/{NoteId} -> 400", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        NoteId: test_collection_1.notes[0]._id
    };
    test.request.body = {
        "note a":"real property"
    };
    done();
});

hooks.before("DELETE /collections/{CollectionId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        NoteId: test_collection_1.notes[0]._id
    };
    done();
});

hooks.before("GET /collections/{CollectionId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[0]._id
    };
    done();
});

hooks.before("DELETE /collections/{CollectionId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[1]._id
    };
    done();
});

hooks.before("GET /collections/{CollectionId}/analyses/{AnalysisId}/files -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[0]._id
    };
    test.request.query.ticket = "";
    done();
});

hooks.before("GET /collections/{CollectionId}/analyses/{AnalysisId}/files/{Filename} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[0]._id,
        Filename: "test-1.dcm"
    };
    test.request.query.ticket = "";
    done();
});

hooks.before("POST /collections/{CollectionId}/analyses/{AnalysisId}/notes -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[0]._id
    };
    done();
});

hooks.before("POST /collections/{CollectionId}/analyses/{AnalysisId}/notes -> 400", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[0]._id
    };
    test.request.body = {
        "not a":"real property"
    };
    done();
});

hooks.before("DELETE /collections/{CollectionId}/analyses/{AnalysisId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        CollectionId : collection_id,
        AnalysisId: test_collection_1.analyses[0]._id,
        NoteId: test_collection_1.analyses[0].notes[0]._id
    };
    done();
});


// set initial test_session_1
hooks.after("GET /sessions -> 200", function(test, done) {
    test_session_1 = test.response.body[0];
    assert.equal(test_session_1.label, "test-session-1");
    done();
});

hooks.before("GET /sessions/{SessionId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    done();
});

// set detailed test_session_1 (including analyses, that are omitted during listing)
hooks.after("GET /sessions/{SessionId} -> 200", function(test, done) {
    test_session_1 = test.response.body;
    done();
});

hooks.after("GET /sessions/{SessionId} -> 200", function(test, done) {
    test_session_1 = test.response.body;
    assert.equal(test_session_1.label, "test-session-1");
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

hooks.before("POST /sessions/{SessionId}/tags -> 200", function(test, done) {
  test.request.params.SessionId = test_session_1._id;
  test.request.body = {
      value: test_session_tag
  };
  done();
});

hooks.before("POST /sessions/{SessionId}/tags -> 400", function(test, done) {
  test.request.params.SessionId = test_session_1._id;
  test.request.body = {
      value: ""
  };
  done();
});

hooks.before("GET /sessions/{SessionId}/tags/{TagValue} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      TagValue: test_session_tag
  };
  done();
});

hooks.before("PUT /sessions/{SessionId}/tags/{TagValue} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      TagValue: test_session_tag
  };
  test_session_tag = 'new-tag-value';
  test.request.body = {
      value: test_session_tag
  };
  done();
});

hooks.before("PUT /sessions/{SessionId}/tags/{TagValue} -> 400", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      TagValue: test_session_tag
  };
  test.request.body = {
      value: ""
  };
  done();
});

hooks.before("DELETE /sessions/{SessionId}/tags/{TagValue} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      TagValue: test_session_tag
  };
  done();
});

hooks.before("GET /sessions/{SessionId}/files/{FileName} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      FileName : "notes.txt"
  };
  test.request.query = {
      "ticket":""
  };
  done();
});

hooks.before("POST /sessions/{SessionId}/notes -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id
  };
  test.request.body = {
      "text":"test note"
  };
  done();
});

hooks.before("POST /sessions/{SessionId}/notes -> 400", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id
  };
  test.request.body = {
      "note a real":"property"
  };
  done();
});

hooks.before("GET /sessions/{SessionId}/notes/{NoteId} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      NoteId: test_session_1.notes[0]._id
  };
  done();
});

hooks.before("PUT /sessions/{SessionId}/notes/{NoteId} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      NoteId: test_session_1.notes[0]._id
  };
  test.request.body = {
      "text":"new note"
  };
  done();
});

hooks.before("PUT /sessions/{SessionId}/notes/{NoteId} -> 400", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      NoteId: test_session_1.notes[0]._id
  };
  test.request.body = {
      "not a real":"property"
  };
  done();
});

hooks.before("DELETE /sessions/{SessionId}/notes/{NoteId} -> 200", function(test, done) {
  test.request.params = {
      SessionId : test_session_1._id,
      NoteId: test_session_1.notes[0]._id
  };
  done();
});

hooks.before("GET /sessions/{SessionId}/acquisitions -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    done();
});

hooks.before("POST /sessions/{SessionId}/analyses -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.query = {"job":"true"};
    test.request.body = {
        "analysis": {
            "label": "Test Analysis 1"
        },
        "job" : {
            "gear": "test-case-gear",
            "inputs": {},
            "tags": ["example"]
        }
    }
    done();
});

hooks.after("POST /sessions/{SessionId}/analyses -> 200", function(test, done) {
    test_session_1_analysis_2_id = test.response.body._id;
    done();
});

hooks.before("GET /sessions/{SessionId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1_analysis_2_id;
    done();
});

hooks.before("DELETE /sessions/{SessionId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1_analysis_2_id;
    done();
});

hooks.before("GET /sessions/{SessionId}/analyses/{AnalysisId}/files -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1.analyses[0]._id;
    test.request.query.ticket = "";
    done();
});

hooks.before("GET /sessions/{SessionId}/analyses/{AnalysisId}/files/{Filename} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1.analyses[0]._id;
    test.request.params.Filename = "test-1.dcm";
    test.request.query.ticket = "";
    done();
});

hooks.before("POST /sessions/{SessionId}/analyses/{AnalysisId}/notes -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1.analyses[0]._id;
    done();
});

hooks.before("POST /sessions/{SessionId}/analyses/{AnalysisId}/notes -> 400", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1.analyses[0]._id;
    test.request.body = {
        "not a":"real property"
    };
    done();
});

hooks.before("DELETE /sessions/{SessionId}/analyses/{AnalysisId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params.SessionId = test_session_1._id;
    test.request.params.AnalysisId = test_session_1.analyses[0]._id;
    test.request.params.NoteId = test_session_1.analyses[0].notes[0]._id;
    done();
});



// set initial test_acquisition_1
hooks.after("GET /acquisitions -> 200", function(test, done) {
    test_acquisition_1 = test.response.body[0];
    assert.equal(test_acquisition_1.label, "test-acquisition-1");
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId} -> 200", function(test, done) {
    test.request.params.AcquisitionId = test_acquisition_1._id;
    done();
});

// set detailed test_acquisition_1 (including analyses, that are omitted during listing)
hooks.after("GET /acquisitions/{AcquisitionId} -> 200", function(test, done) {
    test_acquisition_1 = test.response.body;
    done();
});

hooks.before("POST /acquisitions -> 200", function(test, done) {
    test.request.body.session = test_session_1._id;
    done();
});

hooks.after("POST /acquisitions -> 200", function(test, done) {
    example_acquisition_id = test.response.body._id;
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
    test.request.params.AcquisitionId = example_acquisition_id;
    done();
});

hooks.before("POST /acquisitions/{AcquisitionId}/tags -> 200", function(test, done) {
    test.request.params.AcquisitionId = test_acquisition_1._id;
    test.request.body = {
        "value": test_acquisition_tag
    };
    done();
});

hooks.before("POST /acquisitions/{AcquisitionId}/tags -> 400", function(test, done) {
    test.request.params.AcquisitionId = test_acquisition_1._id;
    test.request.body = {
        "value": test_acquisition_tag,
        "bad property": "not a real property"
    };
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        TagValue : test_acquisition_tag
    };
    done();
});

hooks.before("PUT /acquisitions/{AcquisitionId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        TagValue : test_acquisition_tag
    };
    test_acquisition_tag = "new-tag-value";
    test.request.body = {
        "value": test_acquisition_tag
    };
    done();
});

hooks.before("PUT /acquisitions/{AcquisitionId}/tags/{TagValue} -> 400", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        TagValue : test_acquisition_tag
    };
    test.request.body = {
        "value": test_acquisition_tag,
        "bad property": "not a real property"
    };
    done();
});

hooks.before("DELETE /acquisitions/{AcquisitionId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        TagValue : test_acquisition_tag
    };
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/files/{FileName} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        FileName : "test-1.dcm"
    };
    test.request.query = {
        "ticket":""
    };
    done();
});

hooks.before("POST /acquisitions/{AcquisitionId}/notes -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id
    };
    done();
});

hooks.before("POST /acquisitions/{AcquisitionId}/notes -> 400", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id
    };
    test.request.body.not_real = "invalid property";
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        NoteId: test_acquisition_1.notes[0]._id
    };
    done();
});

hooks.before("PUT /acquisitions/{AcquisitionId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        NoteId: test_acquisition_1.notes[0]._id
    };
    test.request.body = {
        "text":"updated note text"
    };
    done();
});

hooks.before("PUT /acquisitions/{AcquisitionId}/notes/{NoteId} -> 400", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        NoteId: test_acquisition_1.notes[0]._id
    };
    test.request.body = {
        "invalid property":"specified"
    };
    done();
});

hooks.before("DELETE /acquisitions/{AcquisitionId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        NoteId: test_acquisition_1.notes[0]._id
    };
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id
    };
    done();
});

hooks.before("DELETE /acquisitions/{AcquisitionId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[1]._id
    };
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/analyses/{AnalysisId}/files -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id
    };
    test.request.query.ticket = "";
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/analyses/{AnalysisId}/files/{Filename} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id,
        Filename: "test-1.dcm"
    };
    test.request.query.ticket = "";
    done();
});

hooks.before("POST /acquisitions/{AcquisitionId}/analyses/{AnalysisId}/notes -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id
    };
    done();
});

hooks.before("POST /acquisitions/{AcquisitionId}/analyses/{AnalysisId}/notes -> 400", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id
    };
    test.request.body = {
        "not a":"real property"
    };
    done();
});

hooks.before("GET /acquisitions/{AcquisitionId}/analyses/{AnalysisId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id,
        NoteId: test_acquisition_1.analyses[0].notes[0]._id
    };
    done();
});

hooks.before("DELETE /acquisitions/{AcquisitionId}/analyses/{AnalysisId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        AcquisitionId : test_acquisition_1._id,
        AnalysisId: test_acquisition_1.analyses[0]._id,
        NoteId: test_acquisition_1.analyses[0].notes[0]._id
    };
    done();
});


// set initial test_project_1
hooks.after("GET /projects -> 200", function(test, done) {
    test_project_1 = test.response.body[0];
    assert.equal(test_project_1.label, "test-project-1");
    done();
});

hooks.after("POST /projects -> 200", function(test, done) {
    delete_project_id = test.response.body._id;
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

// set detailed test_project_1 (including analyses, that are omitted during listing)
hooks.after("GET /projects/{ProjectId} -> 200", function(test, done) {
    test_project_1 = test.response.body;
    done();
});

hooks.before("PUT /projects/{ProjectId} -> 400", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    test.request.body = {"not_real":"fake property"};
    done();
});

hooks.before("DELETE /projects/{ProjectId} -> 200", function(test, done) {
    test.request.params.ProjectId = delete_project_id;
    done();
});

hooks.before("POST /projects/{ProjectId}/tags -> 200", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    test.request.body = {
        "value":test_project_tag
    };
    done();
});

hooks.before("POST /projects/{ProjectId}/tags -> 400", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    test.request.body = {
        "value":""
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        TagValue : test_project_tag
    };
    done();
});

hooks.before("PUT /projects/{ProjectId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        TagValue : test_project_tag
    };
    test_project_tag = "new-tag-value";
    test.request.body = {
        "value":test_project_tag
    };
    done();
});

hooks.before("PUT /projects/{ProjectId}/tags/{TagValue} -> 400", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        TagValue : test_project_tag
    };
    test.request.body = {
        "value":""
    };
    done();
});

hooks.before("DELETE /projects/{ProjectId}/tags/{TagValue} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        TagValue : test_project_tag
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/files/{FileName} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        FileName : "notes.txt"
    };
    test.request.query = {
        "ticket":""
    };
    done();
});

hooks.before("POST /projects/{ProjectId}/permissions -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id
    };
    test.request.body = {
        "_id":"test@user.com",
        "access":"ro"
    };
    done();
});

hooks.before("POST /projects/{ProjectId}/permissions -> 400", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id
    };
    test.request.body = {
        "not a valid":"permissions entry"
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        UserId: "test@user.com"
    };
    done();
});

hooks.before("PUT /projects/{ProjectId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        UserId: "test@user.com"
    };
    test.request.body = {
        "access":"rw",
        "_id":"test@user.com"
    };
    done();
});

hooks.before("PUT /projects/{ProjectId}/permissions/{UserId} -> 400", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        UserId: "test@user.com"
    };
    test.request.body = {
        "not a valid":"permissions entry"
    };
    done();
});

hooks.before("DELETE /projects/{ProjectId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        UserId: "test@user.com"
    };
    done();
});

hooks.before("POST /projects/{ProjectId}/notes -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id
    };
    test.request.body = {
        "text":"test note"
    };
    done();
});

hooks.before("POST /projects/{ProjectId}/notes -> 400", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id
    };
    test.request.body = {
        "not a real":"property"
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        NoteId: test_project_1.notes[0]._id
    };
    done();
});

hooks.before("PUT /projects/{ProjectId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        NoteId: test_project_1.notes[0]._id
    };
    test.request.body = {
        "text":"updated note"
    };
    done();
});

hooks.before("PUT /projects/{ProjectId}/notes/{NoteId} -> 400", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        NoteId: test_project_1.notes[0]._id
    };
    test.request.body = {
        "not a real":"property"
    };
    done();
});

hooks.before("DELETE /projects/{ProjectId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId : test_project_1._id,
        NoteId: test_project_1.notes[0]._id
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/sessions -> 200", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    done();
});

hooks.before("GET /projects/{ProjectId}/acquisitions -> 200", function(test, done) {
    test.request.params.ProjectId = test_project_1._id;
    done();
});

hooks.before("GET /report/project -> 200", function(test, done) {
    test.request.query = {
        "projects":test_project_1._id
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[0]._id
    };
    done();
});

hooks.before("DELETE /projects/{ProjectId}/analyses/{AnalysisId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[1]._id
    };
    done();
});

hooks.before("GET /projects/{ProjectId}/analyses/{AnalysisId}/files -> 200", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[0]._id
    };
    test.request.query.ticket = "";
    done();
});

hooks.before("GET /projects/{ProjectId}/analyses/{AnalysisId}/files/{Filename} -> 200", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[0]._id,
        Filename: "test-1.dcm"
    };
    test.request.query.ticket = "";
    done();
});

hooks.before("POST /projects/{ProjectId}/analyses/{AnalysisId}/notes -> 200", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[0]._id
    };
    done();
});


hooks.before("POST /projects/{ProjectId}/analyses/{AnalysisId}/notes -> 400", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[0]._id
    };
    test.request.body = {
        "not a":"real property"
    }
    done();
});

hooks.before("DELETE /projects/{ProjectId}/analyses/{AnalysisId}/notes/{NoteId} -> 200", function(test, done) {
    test.request.params = {
        ProjectId: test_project_1._id,
        AnalysisId: test_project_1.analyses[0]._id,
        NoteId: test_project_1.analyses[0].notes[0]._id
    };
    done();
});

hooks.before("GET /devices/{DeviceId} -> 200", function(test, done) {
    test.request.params.DeviceId = device_id;
    done();
});

hooks.before("GET /devices/{DeviceId} -> 404", function(test, done) {
    test.request.params.DeviceId = 'bad_device_id';
    done();
});

// Save Search Tests
hooks.before("POST /savesearches -> 200", function(test, done) {
    test.request.body = {
        "label": "Lable",
        "search": {
            "return_type": "session"
        }
    };
    done();
})
hooks.after("POST /savesearches -> 200", function(test, done) {
    delete_search_id = test.response.body['_id'];
    done();
})

hooks.before("POST /savesearches -> 400", function(test, done) {
    test.request.body = {
        "not-label": "Label"
    };
    done();
})

hooks.after("GET /savesearches -> 200", function(test, done) {
    search_id = test.response.body[0]._id;
    done();
})

hooks.before("GET /savesearches/{SearchId} -> 200", function(test, done) {
    test.request.params = {
        SearchId: search_id
    };
    done();
})

hooks.before("POST /savesearches/{SearchId} -> 200", function(test, done) {
    test.request.params = {
        SearchId: search_id
    };
    test.request.body = {
        "label": "New Label",
        "search": {
            "return_type": "session"
        },
        "_id": search_id
    };
    done();
})

hooks.before("POST /savesearches/{SearchId} -> 400", function(test, done) {
    test.request.params = {
        SearchId: search_id
    };
    test.request.body = {
        "not-label": "Label2"
    };
    done();
})

hooks.before("POST /savesearches/{SearchId}/permissions -> 200", function(test, done) {
    test.request.params = {
        SearchId: search_id
    };
    test.request.body = {
        "access" : "admin",
        "_id": user_id
    };
    done();
})

hooks.before("POST /savesearches/{SearchId}/permissions -> 400", function(test, done) {
    test.request.params = {
        SearchId: search_id
    };
    test.request.body = {
        "not-access" : "admin",
        "not_id": user_id
    };
    done();
})

hooks.before("GET /savesearches/{SearchId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        SearchId: search_id,
        UserId: user_id
    };
    done();
})

hooks.before("PUT /savesearches/{SearchId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        SearchId: search_id,
        UserId: user_id
    };
    test.request.body = {
        "access" : "ro"
    };
    done();
})

hooks.before("PUT /savesearches/{SearchId}/permissions/{UserId} -> 400", function(test, done) {
    test.request.params = {
        SearchId: search_id,
        UserId: user_id
    };
    test.request.body = {
        "access" : "not_an_access_level"
    };
    done();
})

hooks.before("DELETE /savesearches/{SearchId}/permissions/{UserId} -> 200", function(test, done) {
    test.request.params = {
        SearchId: search_id,
        UserId: user_id
    };
    done();
})

hooks.before("DELETE /savesearches/{SearchId} -> 200", function(test, done) {
    test.request.params = {
        SearchId: delete_search_id
    };
    done();
})
