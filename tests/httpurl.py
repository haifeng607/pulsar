'''tests the httpurl stand-alone script.'''
from pulsar import send, make_async, safe_async, is_failure, HttpClient
from pulsar.apps.test import unittest
from pulsar.utils import httpurl

BIN_HOST = 'httpbin.org'
HTTPBIN_URL = 'http://' + BIN_HOST + '/'
HTTPSBIN_URL = 'https://'+ BIN_HOST + '/'


class TestHeaders(unittest.TestCase):
    
    def testServerHeader(self):
        h = httpurl.Headers()
        self.assertEqual(h.kind, 'server')
        self.assertEqual(len(h), 0)
        h['content-type'] = 'text/html'
        self.assertEqual(len(h), 1)
        
    def testClientHeader(self):
        h = httpurl.Headers(kind='client')
        self.assertEqual(h.kind, 'client')
        self.assertEqual(len(h), 0)
        h['content-type'] = 'text/html'
        self.assertEqual(len(h), 1)
        h['server'] = 'bla'
        self.assertEqual(len(h), 1)
        
    def test_accept_content_type(self):
        accept = httpurl.accept_content_type()
        self.assertTrue('text/html' in accept)
        accept = httpurl.accept_content_type(
                        'text/*, text/html, text/html;level=1, */*')
        self.assertTrue('text/html' in accept)
        self.assertTrue('text/plain' in accept)


class TestTools(unittest.TestCase):
    
    def test_to_bytes(self):
        s = httpurl.to_bytes('ciao')
        self.assertTrue(isinstance(s, bytes))
        s2 = httpurl.to_bytes(s)
        self.assertEqual(id(s), id(s2))
        s3 = httpurl.to_bytes(s, 'latin-1')
        self.assertEqual(s, s3)
        self.assertNotEqual(id(s), id(s3))
        
    def test_native_str(self):
        s = 'ciao'
        s2 = httpurl.native_str(s)
        self.assertEqual(id(s), id(s2))


def request_callback(result):
    return result
    
def request(r):
    return make_async(r).addBoth(request_callback)


class TestHttpClient(unittest.TestCase):
    app = None
    with_proxy = False
    proxy_app = None
    timeout = 10
    
    @classmethod
    def setUpClass(cls):
        # Create the HttpBin server by sending this request to the arbiter
        from examples.proxyserver.manage import server as pserver
        from examples.httpbin.manage import server
        concurrency = cls.cfg.concurrency
        s = server(bind='127.0.0.1:0', concurrency=concurrency)
        outcome = send('arbiter', 'run', s)
        yield outcome
        cls.app = outcome.result
        cls.uri = 'http://{0}:{1}'.format(*cls.app.address)
        if cls.with_proxy:
            s = pserver(bind='127.0.0.1:0', concurrency=concurrency)
            outcome = send('arbiter', 'run', s)
            yield outcome
            cls.proxy_app = outcome.result
            cls.proxy_uri = 'http://{0}:{1}'.format(*cls.proxy_app.address)
        
    @classmethod
    def tearDownClass(cls):
        if cls.app is not None:
            yield send('arbiter', 'kill_actor', cls.app.mid)
        if cls.proxy_app is not None:
            yield send('arbiter', 'kill_actor', cls.proxy_app.mid)
        
    def client(self, **kwargs):
        kwargs['timeout'] = self.timeout
        if self.with_proxy:
            kwargs['proxy_info'] = {'http': self.proxy_uri}
        return HttpClient(**kwargs)
    
    def httpbin(self, *suffix):
        if suffix:
            return self.uri + '/' + '/'.join(suffix)
        else:
            return self.uri
    
    def testClient(self):
        http = self.client()
        self.assertTrue('accept-encoding' in http.DEFAULT_HTTP_HEADERS)
        self.assertEqual(http.timeout, self.timeout)
        if self.with_proxy:
            self.assertEqual(http.proxy_info, {'http': self.proxy_uri})
        
    def test_http_200_get(self):
        http = self.client()
        r = make_async(http.get(self.httpbin()))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.response, 'OK')
        self.assertTrue(r.content)
        self.assertEqual(r.url, self.httpbin())
        
    def test_http_200_get_data(self):
        http = self.client()
        r = make_async(http.get(self.httpbin('get'), data={'bla':'foo'}))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.response, 'OK')
        result = r.content_json()
        self.assertEqual(result['args'], {'bla':['foo']})
        self.assertEqual(r.url,
                         self.httpbin(httpurl.iri_to_uri('get',{'bla':'foo'})))
        
    def test_http_200_gzip(self):
        http = self.client()
        r = make_async(http.get(self.httpbin('gzip')))
        yield r
        r = r.result
        headers = r.headers
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.response, 'OK')
        content = r.content_json()
        self.assertTrue(content['gzipped'])
        self.assertTrue(r.headers['content-encoding'],'gzip')
        
    def test_http_400_get(self):
        '''Bad request 400'''
        http = self.client()
        r = make_async(http.get(self.httpbin('status', '400')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.response, 'Bad Request')
        self.assertTrue(r.content)
        self.assertRaises(httpurl.HTTPError, r.raise_for_status)
        
    def test_http_404_get(self):
        '''Not Found 404'''
        http = self.client()
        r = make_async(http.get(self.httpbin('status', '404')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.response, 'Not Found')
        self.assertTrue(r.content)
        self.assertRaises(httpurl.HTTPError, r.raise_for_status)
        
    def test_http_post(self):
        data = (('bla', 'foo'), ('unz', 'whatz'),
                ('numero', '1'), ('numero', '2'))
        http = self.client()
        r = request(http.post(self.httpbin('post'), data=data))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.response, 'OK')
        result = r.content_json()
        self.assertTrue(result['args'])
        self.assertEqual(result['args']['numero'],['1','2'])
        
    def testRedirect(self):
        http = self.client()
        r = make_async(http.get(self.httpbin('redirect','1')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        history = r.request.history
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0].url.endswith('/redirect/1'))
        
    def testRedirect2(self):
        http = self.client()
        r = safe_async(http.get, (self.httpbin('redirect', '5'),),
                                {'max_redirects':2})
        # do this so that the test suite does not fail on the test
        yield r.addBoth(lambda f: [f])
        r = r.result[0]
        self.assertTrue(is_failure(r))
        self.assertTrue(isinstance(r.trace[1], httpurl.TooManyRedirects))
        
    def testResponseHeaders(self):
        http = self.client()
        r = make_async(http.get(self.httpbin('response-headers')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        result = r.content_json()
        self.assertEqual(result['Transfer-Encoding'], 'chunked')
        parser = r.parser
        self.assertTrue(parser.is_chunked())
        
    def test_Cookie(self):
        http = self.client()
        # First set the cookies
        r = make_async(http.get(self.httpbin('cookies', 'set', 'bla', 'foo')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.history)
        self.assertTrue(r.history[0].headers['set-cookie'])
        # Now check if I get them
        r = make_async(http.get(self.httpbin('cookies')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        result = r.content_json()
        self.assertTrue(result['cookies'])
        self.assertEqual(result['cookies']['bla'],'foo')
        # Try without saving cookies
        http = self.client(store_cookies=False)
        r = make_async(http.get(self.httpbin('cookies', 'set', 'bla', 'foo')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.history)
        self.assertTrue(r.history[0].headers['set-cookie'])
        r = make_async(http.get(self.httpbin('cookies')))
        yield r
        r = r.result
        self.assertEqual(r.status_code, 200)
        result = r.content_json()
        self.assertFalse(result['cookies'])

    def test_parse_cookie(self):
        self.assertEqual(httpurl.parse_cookie('invalid:key=true'), {})
        
    def __test_far_expiration(self):
        "Cookie will expire when an distant expiration time is provided"
        response = Response(self.environ())
        response.set_cookie('datetime', expires=datetime(2028, 1, 1, 4, 5, 6))
        datetime_cookie = response.cookies['datetime']
        self.assertEqual(datetime_cookie['expires'], 'Sat, 01-Jan-2028 04:05:06 GMT')

    def __test_max_age_expiration(self):
        "Cookie will expire if max_age is provided"
        response = Response(self.environ())
        response.set_cookie('max_age', max_age=10)
        max_age_cookie = response.cookies['max_age']
        self.assertEqual(max_age_cookie['max-age'], 10)
        self.assertEqual(max_age_cookie['expires'], http.cookie_date(time.time()+10))

    def __test_httponly_cookie(self):
        response = Response(self.environ())
        response.set_cookie('example', httponly=True)
        example_cookie = response.cookies['example']
        # A compat cookie may be in use -- check that it has worked
        # both as an output string, and using the cookie attributes
        self.assertTrue('; httponly' in str(example_cookie))
        self.assertTrue(example_cookie['httponly'])
        

class TestHttpClientWithProxy(TestHttpClient):
    app = None
    with_proxy = True
    proxy_app = None
    server_concurrency = 'process'