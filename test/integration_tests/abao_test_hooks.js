var hooks = require('hooks');

hooks.beforeEach(function (test, done) {
    test.request.query = {
      user: 'admin@user.com',
      root: 'true'
    };
    done();
});

var job_id = '';

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

hooks.skip("GET /users/self/avatar -> 307"); // https://github.com/cybertk/abao/issues/160

hooks.skip("GET /users/{UserId}/avatar -> 307"); // https://github.com/cybertk/abao/issues/160
