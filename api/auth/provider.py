import json
import urllib
import requests
import urlparse
import untangle

from .. import config


def google(access_token):
    provider_config = config.get_item('auth', 'google')
    r = requests.get(provider_config.get('id_endpoint'), headers={'Authorization': 'Bearer ' + access_token})
    if r.ok:
        identity = json.loads(r.content)

        uid = identity.get('email')
        identity.set('uid', uid)

        avatar = identity.get('picture', '')
        # Remove attached size param from URL.
        u = urlparse.urlparse(avatar)
        query = urlparse.parse_qs(u.query)
        query.pop('sz', None)
        u = u._replace(query=urllib.urlencode(query, True))
        avatar = urlparse.urlunparse(u)
        identity.set('avatar', avatar)

        return identity


def orcid(access_token):
    provider_config = config.get_item('auth', 'orcid')
    orcid, access_token = access_token.split(':')
    r = requests.get( provider_config.get('api_endpoint') + '/v2.0/' + orcid +  '/record',
                     headers={'Authorization': 'Bearer ' + access_token})
    if r.ok:
        doc = untangle.parse(r.content)
        data = {}

        # Check if ID is the same from user token
        id = doc.children[0].common_orcid_identifier.common_path.cdata
        if orcid == id:
            data['uid'] = orcid

        # Check if user has visible email
        emails = doc.children[0].person_person.email_emails
        if hasattr(emails, 'email_email'):
            if type(emails.email_email) == list:
                email = next(e.email_email.cdata for e in emails.email_email if e['primary'] == 'true')
            else:
                email = emails.email_email.email_email.cdata

            data['email'] = email
            return data


AuthProviders = {
    'google': google,
    'orcid': orcid,
}