from api import util


def test_hrsize():
    assert util.hrsize(999) == '999B'
    assert util.hrsize(1000) == '1.0KB'
    for i, suffix in enumerate('KMGTPEZY'):
        assert util.hrsize(2**(10*i + 10)) == '1.0{}B'.format(suffix)
        assert util.hrsize(2**(10*i + 10) * 10) == '10{}B'.format(suffix)
    assert util.hrsize(2**80 * 1000) == '1000YB'


def test_mongo_sanitize_fields():
    obj = object()

    input_fields = {
        1: 1,
        2.0: 2.0,
        'foo.bar$baz': 'foo.bar$baz',
        'list': [1, 2.0, 'foo.bar$baz', obj],
        'obj': obj,
    }

    expected_fields = {
        '1': 1,
        '2_0': 2.0,
        'foo_bar-baz': 'foo.bar$baz',
        'list': [1, 2.0, 'foo_bar-baz', obj],
        'obj': obj,
    }

    assert util.mongo_sanitize_fields(input_fields) == expected_fields


def test_deep_update():
    d = {
        'old': 1,
        'both': 1,
        'dict': {
            'old': 1,
            'both': 1,
        },
    }

    u = {
        'both': 2,
        'new': 2,
        'dict': {
            'both': 2,
            'new': 2,
        },
    }

    util.deep_update(d, u)

    assert d == {
        'old': 1,
        'both': 2,
        'new': 2,
        'dict': {
            'old': 1,
            'both': 2,
            'new': 2,
        },
    }


def test_enum():
    # create test enum class
    TestEnum = util.Enum('TestEnum', {
        'foo': 1,
        'bar': 2,
    })

    # test __eq__
    assert TestEnum.foo == TestEnum.foo
    assert TestEnum.foo == 'foo'
    assert TestEnum.foo == u'foo'

    # test __ne__
    assert TestEnum.foo != TestEnum.bar
    assert TestEnum.foo != 'bar'
    assert TestEnum.foo != u'bar'

    # test __str__
    assert str(TestEnum.foo) == 'foo'
