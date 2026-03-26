# Misc Templates (精简版)

## 自动解码
```python
# shared/encoding.py
from shared.encoding import auto_decode
results = auto_decode(data)
```

## 图片 LSB
```python
from PIL import Image
img = Image.open('image.png')
pixels = list(img.getdata())
binary = ''.join(str(p[0] & 1) for p in pixels)
```

## 隐写破解
```bash
python ~/tools/stegseek/stegseek.py image.jpg wordlist.txt
zsteg image.png
```
