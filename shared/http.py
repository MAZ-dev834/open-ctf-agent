#!/usr/bin/env python3
"""HTTP 工具"""

import requests
from urllib.parse import urljoin, urlparse

class HTTP:
    def __init__(self, base_url=None, proxies=None):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.proxies = proxies or {}
    
    def get(self, path='', params=None, **kwargs):
        url = urljoin(self.base_url or '', path)
        return self.session.get(url, params=params, **kwargs)
    
    def post(self, path='', data=None, json=None, **kwargs):
        url = urljoin(self.base_url or '', path)
        return self.session.post(url, data=data, json=json, **kwargs)
    
    def set_headers(self, **kwargs):
        self.session.headers.update(kwargs)
    
    def set_cookie(self, name, value):
        self.session.cookies.set(name, value)

def parse_response(r):
    """解析响应"""
    return {
        'status': r.status_code,
        'headers': dict(r.headers),
        'text': r.text[:500],
        'json': r.json() if r.headers.get('Content-Type', '').startswith('application/json') else None
    }

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        r = requests.get(sys.argv[1])
        print(f"Status: {r.status_code}")
        print(f"Headers: {dict(r.headers)}")
        print(f"Body: {r.text[:200]}")
