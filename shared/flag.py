#!/usr/bin/env python3
"""Flag 验证工具"""

import re
import sys

def validate_flag(flag, pattern=None):
    """验证 flag 格式"""
    if not flag:
        return False, "Flag 为空"
    
    patterns = [
        r'^flag\{.+\}$',
        r'^CTF\{.+\}$',
        r'^FLAG\{.+\}$',
        r'^[a-zA-Z0-9_\-]+$',
    ]
    
    if pattern:
        patterns.insert(0, pattern)
    
    for p in patterns:
        if re.match(p, flag):
            return True, "Valid"
    
    return False, f"Flag 格式不匹配: {flag[:50]}"

def extract_flag(text, pattern=None):
    """从文本中提取 flag"""
    patterns = [
        r'flag\{[^}]+\}',
        r'CTF\{[^}]+\}',
        r'FLAG\{[^}]+\}',
    ]
    
    if pattern:
        patterns.insert(0, pattern)
    
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            return match.group(0)
    
    return None

if __name__ == '__main__':
    if len(sys.argv) > 1:
        flag = sys.argv[1]
    else:
        flag = sys.stdin.read().strip()
    
    valid, msg = validate_flag(flag)
    print(f"{msg} | {flag}")
    sys.exit(0 if valid else 1)
