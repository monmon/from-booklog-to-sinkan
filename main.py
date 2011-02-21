# -*- coding: utf-8 -*-
#
import logging
import re
import urllib

import simplejson
from google.appengine.api import (
    memcache, urlfetch
)
from google.appengine.api.urlfetch import DownloadError
from google.appengine.ext import (
    db, webapp
)
from google.appengine.ext.webapp import util

import config

class CronHandler(webapp.RequestHandler):
    def get(self):
        #author_split_re = re.compile(u'[\s\u30fb]')
        author_split_re = re.compile(u'[\s・]')

        authors = Booklog(config.booklog['user']).get_authors()
        if not authors:
            return

        sinkan = Sinkan({'email': config.sinkan['email'],
                         'password': config.sinkan['password']})
        for author in authors:
            author_data = Author.get_by_key_name(author)
            if author_data:
                logging.debug(author_data.name)
            else:
                full_name = author_split_re.split(author)

                keywords = {}
                keywords['name_sei'] = full_name[0]
                keywords['name_mei'] = full_name[1] if len(full_name) > 1 else ''

                result = sinkan.add(keywords)
                Author(key_name=author, name=author).put()

class Sinkan(object):
    def __init__(self, fields):
        self._url = 'http://sinkan.net/'
        self._form_fields = {
            'login': {
                'action_login_do': 'dummy',
            },
            'add': {
                'action_keywords_add': 'dummy',
                'add'                : 'dummy',
                'store'              : '1',        # 本
            },
        }
        self._session_sess = {
            'id'   : 'DiscoverSESSID',
            'value': '',               # requestで渡しやすいよう id=xxxx が入る
        }

        self.login(fields)

    def add(self, fields):
        # 変なデータを送らないようにするため
        for key in ['title', 'name_sei', 'name_mei', 'publisher', 'keyword']:
            self._form_fields['add'][key] = fields[key].encode('utf8') if fields.get(key) else ''

        csrf = self._get_csrf()
        self._form_fields['add'][csrf['id']] = csrf['value']

        result = self._post(self._form_fields['add'])

        return result

    # login できる or login 状態ならTrue
    def login(self, fields):
        if self._session_sess['value']:
            return True

        for key in ['email', 'password']:
            self._form_fields['login'][key] = fields[key] if fields.get(key) else ''

        for val in self._form_fields.values():
            if not val:
                return False

        result = self._post(self._form_fields['login'])

        if not result:
            return False

        cookies = result.headers.get('set-cookie').split(', ')
        cookies.reverse() # なるべく最後にあるセッションの値が欲しいので逆順にする
        for cookie in cookies:
            if cookie.find(self._session_sess['id']) == 0:
                # DiscoverSESSID=49a1e0a118020e199f0fb9301e026237ddfaa0c2343845de8e3ab6cb0defc0c4; path=/
                self._session_sess['value'] = cookie.split('; ')[0]
                break

        return True if self._session_sess['value'] else False

    # csrf用のkeyもしくは空文字を戻す
    def _get_csrf(self):
        try:
            result = urlfetch.fetch(url='%s/?action_keywords=true' % self._url,
                                    headers={'Cookie': self._session_sess['value']})
        except DownloadError, e:
            return ''

        csrf_key = 'ethna_csrf'
        m = re.compile(r'%s"\svalue="([^"]+)"' % csrf_key).search(result.content)
        if m.groups() and m.group(1):
            return {'id': csrf_key, 'value': m.group(1)}
        else:
            return ''

    def _post(self, form_fields):
        form_data = urllib.urlencode(form_fields)
        try:
            return urlfetch.fetch(url=self._url,
                                  payload=form_data,
                                  method=urlfetch.POST,
                                  headers={
                                      'Cookie': self._session_sess['value'],
                                      'Content-Type': 'application/x-www-form-urlencoded',
                                  },
                                  follow_redirects=False)
        except DownloadError, e:
            return

class Booklog(object):
    def __init__(self, user):
        self._url = 'http://api.booklog.jp/json/%s?category=0&count=100' % user

    def get_authors(self, since_id=None):
        try:
            result = urlfetch.fetch(self._url)
        except DownloadError, e:
            return

        if result.status_code != 200:
            return

        if not since_id:
            since_id = memcache.get('since_id')
        obj = simplejson.loads(result.content)
        authors = []
        for i in xrange(len(obj['books'])):
            if not obj['books'][i]:
                break

            if i == 0:
                memcache.set('since_id', obj['books'][i]['id'])
            elif i == since_id:
                break
            else:
                for author in obj['books'][i]['author'].split(','): # abc,def があり得る
                    authors.append(author)

        return authors

class Author(db.Model):
    name = db.StringProperty(required=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)

    application = webapp.WSGIApplication([('/cron', CronHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
