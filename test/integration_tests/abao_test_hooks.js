var hooks = require('hooks');

hooks.beforeEach(function (test, done) {
    test.request.query = {
      user: 'admin@user.com',
      root: 'true'
    };
    done();
});

hooks.before("GET /users/{UserId} -> 200", function(test, done) {
    test.request.params = {
        UserId: "jane.doe@gmail.com"
    };
    done();
});

hooks.skip("GET /users/self/avatar -> 307"); // https://github.com/cybertk/abao/issues/160
