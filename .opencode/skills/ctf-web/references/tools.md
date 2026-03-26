# Web CTF 工具清单

## Python 库
```bash
pip install requests beautifulsoup4 pyyaml tldextract
pip install sqlmapapi  # SQLMap API
pip install httpie wfuzz jwt_tool pyjwt mitmproxy
```

## 安全工具
```bash
# 扫描器
sudo apt-get install dirbuster ffuf nikto dirsearch sqlmap

# SQL 注入
sqlmap --version

# 其他
gau
waybackurls
paramspider
linkfinder
feroxbuster
nuclei
```

## 常用命令
```bash
# 快速扫描
ffuf -u http://target/FUZZ -w wordlist.txt

# SQLMap
sqlmap -u "http://target" --level=5 --risk=3

# JWT 解析
jwt_tool <token>
```

## 外带测试（OAST）
- `webhook.site`：生成回调 URL，用于 SSRF/Blind XSS/命令注入等外带验证。
