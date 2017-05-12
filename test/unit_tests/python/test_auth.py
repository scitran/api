import datetime
import re

import pytest
import requests_mock


def test_google_auth(config, as_drone, as_public, api_db):
    # inject google auth client_secret into config
    config['auth']['google']['client_secret'] = 'test'

    # try to access api w/ invalid session token
    r = as_public.get('', headers={'Authorization': 'test'})
    assert r.status_code == 401

    # try to login w/o code/auth_type
    r = as_public.post('/login', json={})
    assert r.status_code == 400

    # try to login w/ invalid auth_type
    r = as_public.post('/login', json={'auth_type': 'test', 'code': 'test'})
    assert r.status_code == 400

    with requests_mock.Mocker() as m:
        # try to log in w/ google and invalid code
        m.post(config.auth.google.token_endpoint, status_code=400)
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.status_code == 401

        # try to log in w/ google and invalid token
        m.post(config.auth.google.token_endpoint, json={'access_token': 'test'})
        m.get(config.auth.google.id_endpoint, status_code=400)
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.status_code == 401

        # try to log in w/ google - pretend provider id endpoint doesn't return email
        m.get(config.auth.google.id_endpoint, json={})
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.status_code == 401

        # try to log in w/ google - user not in db (yet)
        m.get(config.auth.google.id_endpoint, json={'email': 'test@gmail.com'})
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.status_code == 402

        # try to log in w/ google - user added but disabled
        as_drone.post('/users', json={
            '_id': 'test@gmail.com', 'disabled': True, 'firstname': 'test', 'lastname': 'test'}).ok
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.status_code == 402

        # try to log in w/ google - invalid refresh token (also mock gravatar 404)
        as_drone.put('/users/test@gmail.com', json={'disabled': False})
        m.head(re.compile('https://gravatar.com/avatar'), status_code=404)
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.status_code == 401
        assert 'gravatar' not in api_db.users.find_one({'_id': 'test@gmail.com'})['avatars']

        # log in (now w/ existing gravatar)
        m.head(re.compile('https://gravatar.com/avatar'))
        m.post(config.auth.google.token_endpoint, json={
            'access_token': 'test', 'expires_in': 60, 'refresh_token': 'test'})
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        assert r.ok
        assert 'gravatar' in api_db.users.find_one({'_id': 'test@gmail.com'})['avatars']
        token_1 = r.json['token']

        # access api w/ valid token
        r = as_public.get('', headers={'Authorization': token_1})
        assert r.ok

        # try to access api w/ expired token - provider fails to refresh token
        api_db.authtokens.update_one({'_id': token_1}, {'$set':
            {'expires': datetime.datetime.now() - datetime.timedelta(seconds=1)}})
        m.post(config.auth.google.refresh_endpoint, status_code=400)
        r = as_public.get('', headers={'Authorization': token_1})
        assert r.status_code == 401
        assert not api_db.authtokens.find({'_id': token_1}).count()

        # access api w/ expired token - test refresh
        m.post(config.auth.google.token_endpoint, json={
            'access_token': 'test', 'expires_in': -1, 'refresh_token': 'test'})
        r = as_public.post('/login', json={'auth_type': 'google', 'code': 'test'})
        token_2 = r.json['token']
        m.post(config.auth.google.refresh_endpoint, json={'access_token': 'test', 'expires_in': 60})
        r = as_public.get('', headers={'Authorization': token_2})
        assert r.ok

        # try to access api w/ expired token but w/o persisted refresh_token
        api_db.authtokens.update_one({'_id': token_2}, {'$set':
            {'expires': datetime.datetime.now() - datetime.timedelta(seconds=1)}})
        api_db.refreshtokens.delete_one({'uid': 'test@gmail.com'})
        r = as_public.get('', headers={'Authorization': token_2})
        assert r.status_code == 401

    # try to logout w/o auth headers
    r = as_public.post('/logout')
    assert r.status_code == 401
