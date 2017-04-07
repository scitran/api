def test_roothandler(as_public):
    r = as_public.get('')
    assert r.ok
