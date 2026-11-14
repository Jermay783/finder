"""Regression checks for Finder proxy transport (no external requests)."""
import unittest
from unittest.mock import patch, Mock
import core

class ProxyTransportTests(unittest.TestCase):
    def test_brave_proxy_forwarded(self):
        response=Mock(status_code=200)
        response.json.return_value={'web':{'results':[]}}
        with patch.object(core.requests.Session,'get',return_value=response) as get:
            with core.requests.Session() as session:
                core.search_brave(session,'fake-key','test',0,'socks5h://127.0.0.1:1080')
        self.assertEqual(get.call_args.kwargs['proxies']['https'],'socks5h://127.0.0.1:1080')

    def test_store_proxy_forwarded(self):
        response=Mock(status_code=200,url='https://example.com/product/x',text='<html></html>')
        response.headers={'Content-Type':'text/html'}
        with patch.object(core.requests,'get',return_value=response) as get:
            core.page_html('https://example.com/product/x',proxy_url='http://127.0.0.1:8080')
        self.assertEqual(get.call_args.kwargs['proxies']['http'],'http://127.0.0.1:8080')

if __name__=='__main__':
    unittest.main()
