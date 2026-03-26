# Misc CTF 工具清单

## 文件分析
```bash
file <file>
binwalk <file>
exiftool <file>
foremost <file> -o output/
```

## 隐写术
```bash
# 图片隐写
steghide extract -sf image.jpg
zsteg -a image.png
stegsolve.jar

# 音频隐写
audacity <file>
sonic-visualiser <file>
```

## 网络分析
```bash
# Wireshark / tshark
tshark -r capture.pcap -Y 'tcp' -T fields -e data

# 常见协议分析
strings <file> | grep -i password
```

## USB HID 分析
```bash
# 提取 USB capdata
tshark -r capture.pcap -Y "usb.capdata" -T fields -e usb.capdata

# 查看 USB 包详情
tshark -r capture.pcap -c 1 -V

# USB 设备统计
tshark -r capture.pcap -q -z endpoints,usb

# 按钮状态统计 (关键!)
awk '{c[$1]++} END{for(k in c) print c[k],k}' deltas.txt | sort -nr
```

**USB HID 7字节格式**: [report_id][btn][dx][dy][wheel]
- btn=1: 可能是鼠标左键/数位板悬停
- btn=2: 可能是鼠标右键/数位板接触画图
- **必须统计按钮分布并分别渲染验证**

## 压缩包
```bash
# 爆破
fcrackzip -u -D -p wordlist.txt archive.zip

# 修复
zip -F broken.zip --out fixed.zip
```

## 常用 Python 库
```bash
pip install pwntools scapy requests
```
