#!/usr/bin/env python3
"""编码/解码工具"""

import base64
import binascii
import urllib.parse
import html
import json

def auto_decode(data):
    """自动尝试多种解码"""
    results = []
    
    if isinstance(data, str):
        data = data.encode()
    
    # Hex
    try:
        dec = binascii.unhexlify(data)
        results.append(('hex', dec))
    except: pass
    
    # Base64
    try:
        dec = base64.b64decode(data, validate=True)
        results.append(('base64', dec))
    except: pass
    
    # Base32
    try:
        dec = base64.b32decode(data, validate=True)
        results.append(('base32', dec))
    except: pass
    
    # URL
    try:
        dec = urllib.parse.unquote(data)
        if dec != data:
            results.append(('url', dec.encode()))
    except: pass
    
    # HTML
    try:
        dec = html.unescape(data.decode())
        if dec != data.decode():
            results.append(('html', dec.encode()))
    except: pass
    
    return results

def encode(data, method='base64'):
    """编码"""
    if isinstance(data, str):
        data = data.encode()
    
    if method == 'base64':
        return base64.b64encode(data)
    elif method == 'hex':
        return binascii.hexlify(data)
    elif method == 'url':
        return urllib.parse.quote(data).encode()
    elif method == 'html':
        return html.escape(data.decode()).encode()
    return data

def decode(data, method):
    """解码"""
    if isinstance(data, str):
        data = data.encode()
    
    if method == 'base64':
        return base64.b64decode(data)
    elif method == 'hex':
        return binascii.unhexlify(data)
    elif method == 'url':
        return urllib.parse.unquote(data).encode()
    elif method == 'html':
        return html.unescape(data.decode()).encode()
    return data

if __name__ == '__main__':
    import sys
    data = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
    
    results = auto_decode(data)
    for method, decoded in results:
        print(f"[{method}] {decoded[:100]}")
