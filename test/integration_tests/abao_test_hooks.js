var hooks = require('hooks');

hooks.beforeEach(function (test, done) {
    test.request.query = {
      user: 'coltonlw@flywheel.io'
    };
    done();
});
