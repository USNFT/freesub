import os
import re
import sys
import json
import time
import uuid
import argparse
import hashlib
import tarfile
import ipaddress
import platform
import zipfile
import base64
import shutil
import socket
import urllib.request
import urllib.parse
import subprocess
import requests
import yaml
import maxminddb
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCE_URLS = [
    "https://wild-cloud-9893.heleimail.workers.dev",
    "https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/output/by-country/v2ray-base64-TW.txt",
    "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/main/configs/all.txt",
    "https://raw.githubusercontent.com/10ium/HiN-VPN/main/subscription/base64/mix",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/protocols/hysteria",
    "https://raw.githubusercontent.com/10ium/telegram-configs-collector/main/security/tls",
    "https://github.com/Au1rxx/free-vpn-subscriptions/raw/main/output/v2ray-base64.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://open.heleimail.workers.dev/",
    "https://www.ermao.net/sub/v2ray/ermao.net",
]

# ==========================================================================
#  可调参数：教程里"改名字 / 加订阅源 / 调间隔"要动的东西都集中在这里
# ==========================================================================
NODE_SUFFIX = "xiaohe"           # 节点名后缀：改成你自己的专属名字
TEST_CONCURRENCY = 25            # 测活并发（I/O 密集，可开大）（GitHub 免费 runner 只有 2 核，原版 25 会拖垮）
PROBE_ATTEMPTS = 1               # 每个节点探测次数（死节点占多数时 2 次=双倍超时），取最快的一次，抗网络抖动
MAX_DELAY_MS = 2500              # 延迟高于此值的节点不进订阅（0 = 不限制）
EXCLUDE_COUNTRIES = {"CN"}       # 出口落在这些国家/地区的节点丢弃（国内落地翻墙用不上）
HY2_ENABLED = True               # 是否用 sing-box 内核真实测活 hysteria2（Xray 不支持该协议）
XRAY_FALLBACK_VERSION = "26.3.27"      # 拿不到最新版本号时的兜底版本
SINGBOX_FALLBACK_VERSION = "1.14.0"
EXIT_IP_APIS = [                 # 探测真实出口 IP 的接口，按顺序兜底
    "https://api.ipify.org?format=json",
    "https://ip.seeip.org/json",
    "https://api.ip.sb/geoip",
    "https://ipinfo.io/json",
]

OUTPUT_DIR = "output"
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "by-country")
RESIDENTIAL_COUNTRY_DIR = os.path.join(OUTPUT_DIR, "residential-by-country")

def ensure_directories():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(COUNTRY_DIR, exist_ok=True)
    os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)

ensure_directories()

# Cloudflare 官方全部 Anycast 网段（严禁进入家宽专区）
CLOUDFLARE_IP_NETWORKS = [
    ipaddress.ip_network("173.245.48.0/20"),
    ipaddress.ip_network("103.21.244.0/22"),
    ipaddress.ip_network("103.22.200.0/22"),
    ipaddress.ip_network("103.31.4.0/22"),
    ipaddress.ip_network("141.101.64.0/18"),
    ipaddress.ip_network("108.162.192.0/18"),
    ipaddress.ip_network("190.93.240.0/20"),
    ipaddress.ip_network("188.114.96.0/20"),
    ipaddress.ip_network("197.234.240.0/22"),
    ipaddress.ip_network("198.41.128.0/17"),
    ipaddress.ip_network("162.158.0.0/15"),
    ipaddress.ip_network("104.16.0.0/13"),
    ipaddress.ip_network("104.24.0.0/14"),
    ipaddress.ip_network("172.64.0.0/13"),
    ipaddress.ip_network("131.0.72.0/22"),
]

def is_cloudflare_cdn_ip(ip_str):
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        for net in CLOUDFLARE_IP_NETWORKS:
            if ip_obj in net:
                return True
    except Exception:
        pass
    return False

# 常见机房与数据中心 ASN
DATACENTER_ASNS = {
    13335, 16509, 14618, 15169, 396982, 8075, 24940, 16276, 
    14061, 31898, 63949, 45102, 132203, 20473, 60068, 55081,
    197540, 51167, 8560, 42708, 201814, 49981, 212238, 46652,
    141995, 200019, 136907, 39351, 9009, 174, 3356, 1299, 2914,
    199180, 202051, 62240, 49304, 34665, 209242, 219337, 44477,
    200651, 202685, 210644, 205628, 51852, 204544, 397373
}

# 严格机房关键词
IDC_KEYWORDS = [
    "hosting", "datacenter", "data center", "cloud", "server", "vps",
    "dedicated", "compute", "colo", "digitalocean", "linode", "ovh",
    "hetzner", "choopa", "vultr", "alibaba", "tencent", "amazon", "aws",
    "google", "microsoft", "oracle", "fastly", "cloudflare", "akamai",
    "netgrid", "m247", "leaseweb", "contabo", "cogent", "zenlayer",
    "ucloud", "lagom", "ipvolume", "hostkey", "selectel", "quadranet",
    "buyvm", "play2go", "fzco"
]

# 核心民用宽带 ASN
TRUE_RESIDENTIAL_ASNS = {
    3462, 9924, 17709, 4780, 18049,
    9269, 3491, 4760, 9304, 17816,
    2516, 4713, 9605, 17511, 17676,
    9318, 4766,
    701, 702, 7922, 20115, 2856, 5089, 5607, 3320, 3209
}

RESIDENTIAL_WHITELIST_KEYWORDS = [
    "broadband", "dynamic", "pppoe", "cust", "dial", "user", "home",
    "residential", "ftth", "cable", "dsl", "consumer",
    "chunghwa", "hinet", "cht", "data communication business group",
    "taiwan fixed network", "kbro", "far eastone", "tfn",
    "hkbn", "hong kong broadband", "pccw", "hkt", "hgc", "smartone",
    "so-net", "kddi", "softbank", "ocn", "plala", "sk broadband", "korea telecom",
    "comcast", "charter", "at&t", "verizon", "spectrum", "cox", "vodafone",
    "deutsche telekom", "telekom", "orange", "bt-central", "virgin media"
]

COUNTRY_NAMES = {
    "HK": "中国香港 (Hong Kong)",
    "TW": "中国台湾 (Taiwan)",
    "JP": "日本 (Japan)",
    "SG": "新加坡 (Singapore)",
    "US": "美国 (United States)",
    "KR": "韩国 (South Korea)",
    "DE": "德国 (Germany)",
    "GB": "英国 (United Kingdom)",
    "CA": "加拿大 (Canada)",
    "FR": "法国 (France)",
    "NL": "荷兰 (Netherlands)",
    "RU": "俄罗斯 (Russia)",
    "IN": "印度 (India)",
    "AU": "澳大利亚 (Australia)",
    "IT": "意大利 (Italy)",
    "ES": "西班牙 (Spain)",
    "TR": "土耳其 (Turkey)",
    "AE": "阿联酋 (UAE)",
    "AT": "奥地利 (Austria)",
    "AU": "澳大利亚 (Australia)",
    "BE": "比利时 (Belgium)",
    "BG": "保加利亚 (Bulgaria)",
    "BR": "巴西 (Brazil)",
    "CA": "加拿大 (Canada)",
    "CH": "瑞士 (Switzerland)",
    "CY": "塞浦路斯 (Cyprus)",
    "CZ": "捷克 (Czechia)",
    "DE": "德国 (Germany)",
    "DK": "丹麦 (Denmark)",
    "EE": "爱沙尼亚 (Estonia)",
    "EG": "埃及 (Egypt)",
    "ES": "西班牙 (Spain)",
    "FI": "芬兰 (Finland)",
    "FR": "法国 (France)",
    "GB": "英国 (United Kingdom)",
    "GR": "希腊 (Greece)",
    "HK": "中国香港 (Hong Kong)",
    "HU": "匈牙利 (Hungary)",
    "ID": "印度尼西亚 (Indonesia)",
    "IE": "爱尔兰 (Ireland)",
    "IL": "以色列 (Israel)",
    "IN": "印度 (India)",
    "IT": "意大利 (Italy)",
    "JP": "日本 (Japan)",
    "KR": "韩国 (South Korea)",
    "KZ": "哈萨克斯坦 (Kazakhstan)",
    "LU": "卢森堡 (Luxembourg)",
    "LV": "拉脱维亚 (Latvia)",
    "MX": "墨西哥 (Mexico)",
    "MY": "马来西亚 (Malaysia)",
    "MU": "毛里求斯 (Mauritius)",
    "NL": "荷兰 (Netherlands)",
    "NO": "挪威 (Norway)",
    "NZ": "新西兰 (New Zealand)",
    "PH": "菲律宾 (Philippines)",
    "PL": "波兰 (Poland)",
    "PT": "葡萄牙 (Portugal)",
    "RO": "罗马尼亚 (Romania)",
    "RS": "塞尔维亚 (Serbia)",
    "RU": "俄罗斯 (Russia)",
    "SC": "塞舌尔 (Seychelles)",
    "SE": "瑞典 (Sweden)",
    "SG": "新加坡 (Singapore)",
    "TH": "泰国 (Thailand)",
    "TR": "土耳其 (Turkey)",
    "TW": "中国台湾 (Taiwan)",
    "UA": "乌克兰 (Ukraine)",
    "US": "美国 (United States)",
    "UZ": "乌兹别克斯坦 (Uzbekistan)",
    "VN": "越南 (Vietnam)",
    "ZA": "南非 (South Africa)",
    "OTHER": "其他地区 (Other)",
}

VALID_SS_CIPHERS = {
    "aes-128-gcm", "aes-192-gcm", "aes-256-gcm",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305", "aes-128-ctr", "aes-192-ctr",
    "aes-256-ctr", "aes-128-cfb", "aes-192-cfb", "aes-256-cfb", "rc4-md5"
}

def get_country_flag(country_code):
    if not country_code or country_code.upper() in ["OTHER", "ZZ", "XX", "T1"]:
        return "🌐"
    try:
        cc = country_code.upper()
        if len(cc) == 2 and cc.isalpha():
            return chr(ord(cc[0]) + 127397) + chr(ord(cc[1]) + 127397)
    except Exception:
        pass
    return "🌐"

def safe_download(url, dest_path):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Accept': '*/*'
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)

def is_windows():
    return platform.system().lower().startswith("win")

def xray_binary_name():
    return "xray.exe" if is_windows() else "xray"

def singbox_binary_name():
    return "sing-box.exe" if is_windows() else "sing-box"

def get_latest_release_version(repo, fallback):
    """从 GitHub API 取最新 release 版本号，失败则用兜底版本（原版把内核锁死在 1.8.24，太旧）。"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"User-Agent": "freesub-updater", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            tag = json.load(resp).get("tag_name", "").strip().lstrip("v")
        if re.fullmatch(r"\d+(\.\d+)+", tag):
            return tag
        print(f"[!] {repo} 返回了异常版本号 {tag!r}，使用兜底版本 {fallback}")
    except Exception as e:
        print(f"[!] 获取 {repo} 最新版本失败({e})，使用兜底版本 {fallback}")
    return fallback

def setup_environment():
    print("[*] 正在准备离线数据库与测活内核...")
    if not os.path.exists("Country.mmdb"):
        safe_download("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb", "Country.mmdb")
    if not os.path.exists("ASN.mmdb"):
        safe_download("https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb", "ASN.mmdb")

    xray_bin = xray_binary_name()
    if not os.path.exists(xray_bin):
        ver = get_latest_release_version("XTLS/Xray-core", XRAY_FALLBACK_VERSION)
        asset = "Xray-windows-64.zip" if is_windows() else "Xray-linux-64.zip"
        print(f"[*] 正在下载官方 Xray-core v{ver} 测活内核 ({asset})...")
        safe_download(f"https://github.com/XTLS/Xray-core/releases/download/v{ver}/{asset}", "xray.zip")
        with zipfile.ZipFile("xray.zip", 'r') as zip_ref:
            zip_ref.extract(xray_bin, ".")
        if not is_windows():
            os.chmod(xray_bin, 0o755)
        if os.path.exists("xray.zip"):
            os.remove("xray.zip")

    sb_bin = singbox_binary_name()
    if HY2_ENABLED and not os.path.exists(sb_bin):
        ver = get_latest_release_version("SagerNet/sing-box", SINGBOX_FALLBACK_VERSION)
        asset = f"sing-box-{ver}-windows-amd64.zip" if is_windows() else f"sing-box-{ver}-linux-amd64.tar.gz"
        print(f"[*] 正在下载官方 sing-box v{ver} 内核（hysteria2 真测活用）...")
        safe_download(f"https://github.com/SagerNet/sing-box/releases/download/v{ver}/{asset}", asset)
        if asset.endswith(".zip"):
            with zipfile.ZipFile(asset, 'r') as z:
                for name in z.namelist():
                    if name.endswith("/" + sb_bin) or name.endswith(sb_bin):
                        with z.open(name) as src, open(sb_bin, "wb") as dst:
                            shutil.copyfileobj(src, dst)
        else:
            with tarfile.open(asset, 'r:gz') as t:
                for member in t.getmembers():
                    if member.name.endswith("/" + sb_bin):
                        member.name = sb_bin
                        t.extract(member, ".")
        if not is_windows():
            os.chmod(sb_bin, 0o755)
        if os.path.exists(asset):
            os.remove(asset)

def extract_nodes_from_text(text):
    results = set()
    if not text:
        return results
    for _ in range(3):
        try:
            padded = text.strip() + '=' * (-len(text.strip()) % 4)
            decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
            if any(p in decoded for p in ["vmess://", "vless://", "ss://", "trojan://", "hy2://", "hysteria2://"]):
                text += "\n" + decoded
        except Exception:
            pass

    pattern = r'((?:vmess|vless|ss|trojan|hysteria2|hy2)://[^\s"\'<>]+)'
    for m in re.findall(pattern, text):
        clean = m.strip().rstrip(".,;\"')")
        results.add(clean)
    return results

def fetch_raw_nodes():
    nodes = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    print("[*] 正在抓取全部可用节点池...")
    for url in SOURCE_URLS:
        try:
            resp = requests.get(url, headers=headers, timeout=25)
            if resp.status_code == 200:
                extracted = extract_nodes_from_text(resp.text)
                nodes.update(extracted)
                print(f"[+] 抓取成功: {url} -> 获得 {len(extracted)} 个节点")
            else:
                print(f"[!] 响应异常 {url} -> HTTP {resp.status_code}")
        except Exception as e:
            print(f"[!] 拉取失败 {url}: {e}")
    print(f"[*] 初始抓取总量: {len(nodes)} 个")
    return list(nodes)

def parse_node_to_xray_outbound(node_str):
    try:
        if node_str.startswith("vless://"):
            m = re.search(r"vless://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if not m:
                return None, None, None, "vless"
            uuid_str, server, port_s, query = m.groups()
            port = int(port_s)
            params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))

            outbound = {
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": server,
                        "port": port,
                        "users": [{"id": uuid_str, "encryption": params.get("encryption", "none"),
                                   "flow": params.get("flow", "")}]
                    }]
                },
                "streamSettings": {
                    "network": params.get("type", "tcp"),
                    "security": params.get("security", "none")
                }
            }
            if params.get("security") == "reality":
                pbk = params.get("pbk", "")
                if not pbk:
                    return None, None, None, "vless"
                outbound["streamSettings"]["realitySettings"] = {
                    "serverName": params.get("sni", server),
                    "publicKey": pbk,
                    "shortId": params.get("sid", ""),
                    "fingerprint": params.get("fp", "chrome")
                }
            elif params.get("security") == "tls":
                outbound["streamSettings"]["tlsSettings"] = {
                    "serverName": params.get("sni", server),
                    "allowInsecure": True
                }
            if params.get("type") == "ws":
                outbound["streamSettings"]["wsSettings"] = {
                    "path": urllib.parse.unquote(params.get("path", "/")),
                    "headers": {"Host": params.get("host", server)}
                }
            return outbound, server, port, "vless"

        elif node_str.startswith("vmess://"):
            b64 = node_str[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            server = str(data.get("add", "")).strip()
            port = int(data.get("port", 0))
            uuid_str = str(data.get("id", "")).strip()
            if not server or port <= 0:
                return None, None, None, "vmess"
            
            is_tls = data.get("tls") in ["tls", "1"]
            outbound = {
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": server,
                        "port": port,
                        "users": [{"id": uuid_str, "alterId": int(data.get("aid", 0)), "security": "auto"}]
                    }]
                },
                "streamSettings": {
                    "network": data.get("net", "tcp"),
                    "security": "tls" if is_tls else "none"
                }
            }
            if is_tls:
                outbound["streamSettings"]["tlsSettings"] = {
                    "serverName": str(data.get("host", server)).strip(),
                    "allowInsecure": True
                }
            if data.get("net") == "ws":
                outbound["streamSettings"]["wsSettings"] = {
                    "path": data.get("path", "/"),
                    "headers": {"Host": str(data.get("host", server)).strip()}
                }
            return outbound, server, port, "vmess"

        elif node_str.startswith("trojan://"):
            m = re.search(r"trojan://([^@]+)@([^:]+):(\d+)\??(.*)", node_str)
            if not m:
                return None, None, None, "trojan"
            password, server, port_s, query = m.groups()
            port = int(port_s)
            params = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
            
            outbound = {
                "protocol": "trojan",
                "settings": {
                    "servers": [{"address": server, "port": port, "password": password}]
                },
                "streamSettings": {
                    "network": params.get("type", "tcp"),
                    "security": "tls",
                    "tlsSettings": {"serverName": params.get("sni", server), "allowInsecure": True}
                }
            }
            return outbound, server, port, "trojan"

        elif node_str.startswith("ss://"):
            raw = node_str[5:].split("#")[0].strip()
            server, port, password, cipher = "", 0, "", ""
            
            if "@" in raw:
                user_info, host_info = raw.split("@", 1)
                user_info += '=' * (-len(user_info) % 4)
                try:
                    dec = base64.b64decode(user_info).decode('utf-8', errors='ignore')
                    if ":" in dec:
                        cipher, password = dec.split(":", 1)
                except Exception:
                    pass
                if ":" in host_info:
                    server, port_s = host_info.split("/")[0].split("?")[0].split(":", 1)
                    port = int(port_s)
            else:
                padded = raw + '=' * (-len(raw) % 4)
                try:
                    dec = base64.b64decode(padded).decode('utf-8', errors='ignore')
                    if "@" in dec:
                        u_info, h_info = dec.split("@", 1)
                        if ":" in u_info:
                            cipher, password = u_info.split(":", 1)
                        if ":" in h_info:
                            server, port_s = h_info.split("/")[0].split("?")[0].split(":", 1)
                            port = int(port_s)
                except Exception:
                    pass

            if server and port > 0:
                outbound = {
                    "protocol": "shadowsocks",
                    "settings": {
                        "servers": [{"address": server, "port": port, "method": cipher or "chacha20-ietf-poly1305", "password": password}]
                    }
                }
                return outbound, server, port, "ss"

        elif node_str.startswith("hy2://") or node_str.startswith("hysteria2://"):
            prefix = "hy2://" if node_str.startswith("hy2://") else "hysteria2://"
            raw = node_str[len(prefix):].split("#")[0]
            m = re.search(r"([^@]+)@([^:/?#]+):(\d+)", raw)
            if m:
                auth, server, port_s = m.groups()
                port = int(port_s)
                outbound = {
                    "protocol": "hysteria2",
                    "settings": {
                        "servers": [{"address": server, "port": port, "password": auth}]
                    }
                }
                return outbound, server, port, "hysteria2"
    except Exception:
        pass
    return None, None, None, "unknown"

def convert_to_clash_dict(node_str, name):
    try:
        outbound, server, port, proto = parse_node_to_xray_outbound(node_str)
        if not outbound:
            return None
        if proto == "vless":
            user = outbound["settings"]["vnext"][0]["users"][0]
            stream = outbound["streamSettings"]
            proxy = {
                "name": name,
                "type": "vless",
                "server": server,
                "port": port,
                "uuid": user["id"],
                "udp": True,
                "tls": stream.get("security") in ["tls", "reality"],
                "skip-cert-verify": True
            }
            if stream.get("security") == "reality":
                r_set = stream.get("realitySettings", {})
                proxy["reality-opts"] = {"public-key": r_set.get("publicKey", "")}
                if r_set.get("shortId"):
                    proxy["reality-opts"]["short-id"] = r_set["shortId"]
                proxy["servername"] = r_set.get("serverName", server)
                proxy["client-fingerprint"] = r_set.get("fingerprint", "chrome")
                if user.get("flow"):
                    proxy["flow"] = user["flow"]
            elif stream.get("security") == "tls":
                proxy["servername"] = stream.get("tlsSettings", {}).get("serverName", server)
            if stream.get("network") == "ws":
                proxy["network"] = "ws"
                proxy["ws-opts"] = stream.get("wsSettings", {})
            return proxy
        elif proto == "vmess":
            user = outbound["settings"]["vnext"][0]["users"][0]
            stream = outbound["streamSettings"]
            proxy = {
                "name": name,
                "type": "vmess",
                "server": server,
                "port": port,
                "uuid": user["id"],
                "alterId": user.get("alterId", 0),
                "cipher": "auto",
                "udp": True,
                "tls": stream.get("security") == "tls",
                "skip-cert-verify": True
            }
            if stream.get("security") == "tls":
                proxy["servername"] = stream.get("tlsSettings", {}).get("serverName", server)
            if stream.get("network") == "ws":
                proxy["network"] = "ws"
                proxy["ws-opts"] = stream.get("wsSettings", {})
            return proxy
        elif proto == "trojan":
            srv = outbound["settings"]["servers"][0]
            return {
                "name": name,
                "type": "trojan",
                "server": server,
                "port": port,
                "password": srv["password"],
                "udp": True,
                "sni": stream.get("tlsSettings", {}).get("serverName", server),
                "skip-cert-verify": True
            }
        elif proto == "ss":
            srv = outbound["settings"]["servers"][0]
            return {
                "name": name,
                "type": "ss",
                "server": server,
                "port": port,
                "cipher": srv["method"],
                "password": srv["password"],
                "udp": True
            }
        elif proto == "hysteria2":
            srv = outbound["settings"]["servers"][0]
            return {
                "name": name,
                "type": "hysteria2",
                "server": server,
                "port": port,
                "password": srv["password"],
                "udp": True,
                "skip-cert-verify": True
            }
    except Exception:
        pass
    return None

def test_single_node_hy2_singbox(node_tuple):
    """用 sing-box 内核真实测活 hysteria2 节点（Xray-core 不支持该协议，原版直接跳过=假支持）。"""
    raw_node, server, port, proto = node_tuple
    outbound, _, _, _ = parse_node_to_xray_outbound(raw_node)
    if not outbound:
        return None

    query = raw_node.split("?", 1)[1] if "?" in raw_node else ""
    qparams = dict(re.findall(r"([^=&#]+)=([^&#]*)", query))
    srv = outbound["settings"]["servers"][0]
    sni = qparams.get("sni", srv["address"])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        socks_port = s.getsockname()[1]

    cfg_path = f"singbox_tmp_{uuid.uuid4().hex}.json"
    config = {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": socks_port}],
        "outbounds": [{
            "type": "hysteria2", "server": srv["address"], "server_port": srv["port"],
            "password": srv["password"],
            "tls": {"enabled": True, "insecure": True, "server_name": sni},
        }],
    }
    with open(cfg_path, "w") as f:
        json.dump(config, f)

    proc = subprocess.Popen([f"./{singbox_binary_name()}", "run", "-c", cfg_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)  # sing-box 起 UDP 隧道比 xray 慢，多等一会

    proxies = {"http": f"socks5h://127.0.0.1:{socks_port}", "https": f"socks5h://127.0.0.1:{socks_port}"}
    delay_ms, exit_ip, is_confirmed_exit, success = 0, None, False, False
    try:
        for _ in range(max(1, PROBE_ATTEMPTS)):
            start_t = time.time()
            try:
                resp = requests.get("https://www.google.com/generate_204", proxies=proxies, timeout=5.0)
            except Exception:
                continue
            if resp.status_code in [200, 204]:
                d = int((time.time() - start_t) * 1000)
                if 30 < d < 6300:
                    delay_ms = d
                    success = True
                    break
        if success:
            for check_url in EXIT_IP_APIS:
                try:
                    ip_resp = requests.get(check_url, proxies=proxies, timeout=3.0)
                    if ip_resp.status_code == 200:
                        data = ip_resp.json()
                        if isinstance(data, dict) and data.get("ip"):
                            exit_ip = data["ip"]
                            is_confirmed_exit = True
                            break
                except Exception:
                    pass
            if not exit_ip:
                try:
                    exit_ip = socket.gethostbyname(server)
                except Exception:
                    exit_ip = server
    finally:
        proc.kill()
        proc.wait()
        try:
            os.remove(cfg_path)
        except Exception:
            pass

    if success and exit_ip:
        return (raw_node, server, port, proto, exit_ip, delay_ms, is_confirmed_exit)
    return None

def test_single_node_xray(node_tuple):
    raw_node, server, port, proto = node_tuple
    outbound, _, _, _ = parse_node_to_xray_outbound(raw_node)
    if not outbound or proto == "hysteria2":
        return None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        socks_port = s.getsockname()[1]

    task_id = uuid.uuid4().hex
    cfg_path = f"xray_tmp_{task_id}.json"

    config = {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": False}
        }],
        "outbounds": [outbound]
    }
    
    with open(cfg_path, "w") as f:
        json.dump(config, f)

    proc = subprocess.Popen(["./xray", "-c", cfg_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.35)

    success = False
    delay_ms = 0
    exit_ip = None
    is_confirmed_exit = False
    proxies = {
        "http": f"socks5h://127.0.0.1:{socks_port}",
        "https": f"socks5h://127.0.0.1:{socks_port}"
    }
    try:
        # 连续多次探测取最快值：单次握手受抖动影响大，容易误杀/误留
        delays = []
        for _ in range(max(1, PROBE_ATTEMPTS)):
            start_t = time.time()
            try:
                resp = requests.get("https://www.google.com/generate_204", proxies=proxies, timeout=4.5)
            except Exception:
                continue
            if resp.status_code in [200, 204]:
                d = int((time.time() - start_t) * 1000)
                if 30 < d < 6300:
                    delays.append(d)
        if delays:
            delay_ms = min(delays)
            # 严格通过代理穿透向公网 API 获取真实出网 IP（多 API 兜底，防单点失效清空家宽专区）
            for check_url in EXIT_IP_APIS:
                try:
                    ip_resp = requests.get(check_url, proxies=proxies, timeout=3.0)
                    if ip_resp.status_code == 200:
                        data = ip_resp.json()
                        fetched = data.get("ip") if isinstance(data, dict) else None
                        if fetched:
                            exit_ip = fetched
                            is_confirmed_exit = True
                            break
                except Exception:
                    pass

            # 若无法穿透拿到落地 IP，仅以普通可用出库，绝不打上真出口标签
            if not exit_ip:
                try:
                    exit_ip = socket.gethostbyname(server)
                except Exception:
                    exit_ip = server
            success = True
    except Exception:
        success = False
    finally:
        proc.kill()
        proc.wait()
        try:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)
        except Exception:
            pass

    if success and exit_ip:
        return (raw_node, server, port, proto, exit_ip, delay_ms, is_confirmed_exit)
    return None

def run_real_delay_test_xray(candidates):
    tcp_nodes = [c for c in candidates if c[3] != "hysteria2"]
    hy2_nodes = [c for c in candidates if c[3] == "hysteria2"]
    if HY2_ENABLED and hy2_nodes and os.path.exists(singbox_binary_name()):
        print(f"[*] 启动真实双向网络通道测活：{len(tcp_nodes)} 个 Xray 节点 + {len(hy2_nodes)} 个 hysteria2 节点(sing-box)")
    else:
        print(f"[*] 启动真实双向网络通道测活，候选节点数: {len(tcp_nodes)}...")
        if hy2_nodes:
            print(f"[!] sing-box 内核不可用，跳过 {len(hy2_nodes)} 个 hysteria2 节点（不测活就不出库，避免混入死节点）")
    alive = []
    with ThreadPoolExecutor(max_workers=TEST_CONCURRENCY) as executor:
        futures = [executor.submit(test_single_node_xray, item) for item in tcp_nodes]
        if HY2_ENABLED and hy2_nodes and os.path.exists(singbox_binary_name()):
            futures += [executor.submit(test_single_node_hy2_singbox, item) for item in hy2_nodes]
        for future in as_completed(futures):
            try:
                res = future.result()
            except Exception:
                res = None
            if res:
                alive.append(res)
                if len(alive) % 20 == 0:
                    print(f"[+] 当前已确认真实通畅节点: {len(alive)} 个")
    print(f"[+] 测活完成！真实可用落地节点总数: {len(alive)}")
    return alive

def rename_node_link(raw_link, new_name):
    try:
        if raw_link.startswith("vmess://"):
            b64 = raw_link[8:]
            b64 += '=' * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode('utf-8', errors='ignore'))
            data["ps"] = new_name
            new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode('utf-8')).decode('utf-8')
            return f"vmess://{new_b64}"
        elif any(raw_link.startswith(p) for p in ["vless://", "trojan://", "ss://", "hy2://", "hysteria2://"]):
            base_part = raw_link.split("#")[0].strip()
            return f"{base_part}#{new_name}"
    except Exception:
        pass
    return raw_link

def get_rdns_host(ip):
    try:
        socket.setdefaulttimeout(1.2)
        host, _, _ = socket.gethostbyaddr(ip)
        return host.lower()
    except Exception:
        return ""

def is_verified_residential_offline(ip, org_str, asn):
    if asn in TRUE_RESIDENTIAL_ASNS:
        return True

    info = f"{org_str} {get_rdns_host(ip)}".lower()
    for kw in IDC_KEYWORDS:
        if kw in info:
            return False
            
    for r_kw in RESIDENTIAL_WHITELIST_KEYWORDS:
        if r_kw in info:
            return True

    return False

def classify_and_filter(alive_nodes):
    country_reader = maxminddb.open_database("Country.mmdb")
    asn_reader = maxminddb.open_database("ASN.mmdb")
    verified = []

    def classify_item(item):
        raw_node, server, port, proto, exit_ip, delay, is_confirmed_exit = item

        country_code = "OTHER"
        try:
            c = country_reader.get(exit_ip)
            if c and "country" in c:
                code = c["country"]["iso_code"]
                if code not in ["T1", "A1", "A2", "OTHER"]:
                    country_code = code.upper()
        except Exception:
            pass

        # 出口在排除清单（如 CN）的节点直接丢弃：对自己翻墙没用的落地
        if country_code in EXCLUDE_COUNTRIES:
            return None

        # 核心拦截：如果未拿到经代理穿透的真实出网 IP，或命中 Cloudflare CDN，一票否决家宽属性
        if not is_confirmed_exit or is_cloudflare_cdn_ip(exit_ip):
            is_residential = False
        else:
            is_residential = False
            try:
                a = asn_reader.get(exit_ip)
                asn = a.get("autonomous_system_number", 0) if a else 0
                org = str(a.get("autonomous_system_organization", "")).lower() if a else ""
                
                if asn not in DATACENTER_ASNS:
                    is_residential = is_verified_residential_offline(exit_ip, org, asn)
            except Exception:
                pass

        c_dict = convert_to_clash_dict(raw_node, "temp")
        if not c_dict:
            return None

        return {
            "link": raw_node,
            "clash_proxy": c_dict,
            "country": str(country_code).upper(),
            "is_residential": is_residential,
            "exit_ip": exit_ip,
            "port": port,
            "proto": proto,
            "delay": delay
        }

    print("[*] 正在解析真实出口国家并鉴定住宅属性...")
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(classify_item, item) for item in alive_nodes]
        for f in as_completed(futures):
            res = f.result()
            if res:
                verified.append(res)

    country_reader.close()
    asn_reader.close()

    # 关键防线：普通池保留不同配置，家宽专区强制单 IP 严格去重（杜绝 40 个重复高危 IP 刷屏）
    unique_all = []
    seen_all = set()
    seen_res_ips = set()

    for item in verified:
        link_core = item["link"].split("#")[0].strip()
        link_fp = hashlib.sha256(link_core.encode("utf-8")).hexdigest()[:16]
        all_key = f"{item['proto']}://{item['exit_ip']}:{item['port']}_{link_fp}"
        if all_key not in seen_all:
            seen_all.add(all_key)
            
            # 若标记为家宽，但该物理出口 IP 已存在，直接降级为普通节点，绝不重复生成
            if item["is_residential"]:
                if item["exit_ip"] in seen_res_ips:
                    item["is_residential"] = False
                else:
                    seen_res_ips.add(item["exit_ip"])
            unique_all.append(item)

    print(f"[*] 智能去重与家宽防刷完成，出库总节点: {len(unique_all)} 个，纯净独立家宽: {len(seen_res_ips)} 个")
    return unique_all

def export_clash_yaml(clash_proxies, filepath):
    names = [p["name"] for p in clash_proxies]
    config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": clash_proxies,
        "proxy-groups": [
            {"name": "PROXIES", "type": "select", "proxies": ["AUTO"] + names},
            {"name": "AUTO", "type": "url-test", "url": "https://www.google.com/generate_204", "interval": 300, "proxies": names}
        ],
        "rules": ["MATCH,PROXIES"]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)

def export_singbox_json(clash_proxies, filepath):
    names = [p["name"] for p in clash_proxies]
    outbounds = [
        {"type": "selector", "tag": "select", "outbounds": ["auto"] + names},
        {"type": "urltest", "tag": "auto", "outbounds": names, "url": "https://www.google.com/generate_204"},
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"}
    ]
    config = {"version": 1, "outbounds": outbounds}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def format_node_group(nodes_list, res_tag_force=False):
    formatted_links = []
    formatted_proxies = []
    
    for idx, item in enumerate(nodes_list, start=1):
        cc = item["country"]
        flag = get_country_flag(cc)
        c_name = COUNTRY_NAMES.get(cc, cc)
        
        is_res = item["is_residential"] or res_tag_force
        tag = " (家宽)" if is_res else ""
        node_name = f"{flag} {c_name} {idx:02d}{tag} - {NODE_SUFFIX}"
        
        new_proxy = dict(item["clash_proxy"])
        new_proxy["name"] = node_name
        formatted_proxies.append(new_proxy)
        
        new_link = rename_node_link(item["link"], node_name)
        formatted_links.append(new_link)
        
    return formatted_links, formatted_proxies

def sort_by_delay(nodes_list):
    """按延迟升序排列：客户端里节点从快到慢，用户直接选第一个。"""
    return sorted(nodes_list, key=lambda n: n.get("delay", 99999))

def export_subscriptions(verified_nodes):
    ensure_directories()
    # 延迟质量门槛（原版不过滤、按测活完成乱序出库）
    if MAX_DELAY_MS:
        before = len(verified_nodes)
        verified_nodes = [n for n in verified_nodes if n.get("delay", 99999) <= MAX_DELAY_MS]
        dropped = before - len(verified_nodes)
        if dropped:
            print(f"[*] 延迟 >{MAX_DELAY_MS}ms 的高延迟节点已剔除: {dropped} 个")
    verified_nodes = sort_by_delay(verified_nodes)
    residential_nodes = sort_by_delay([n for n in verified_nodes if n["is_residential"]])
    non_residential_nodes = sort_by_delay([n for n in verified_nodes if not n["is_residential"]])

    # 1. 导出全量总订阅
    all_links, all_proxies = format_node_group(verified_nodes)
    with open(os.path.join(OUTPUT_DIR, "v2ray.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(all_links).encode()).decode())
    export_clash_yaml(all_proxies, os.path.join(OUTPUT_DIR, "clash.yaml"))
    export_singbox_json(all_proxies, os.path.join(OUTPUT_DIR, "singbox.json"))

    # 2. 导出家宽总订阅
    res_links, res_proxies = format_node_group(residential_nodes, res_tag_force=True)
    with open(os.path.join(OUTPUT_DIR, "residential.txt"), "w", encoding="utf-8") as f:
        f.write(base64.b64encode("\n".join(res_links).encode()).decode())
    if res_proxies:
        export_clash_yaml(res_proxies, os.path.join(OUTPUT_DIR, "residential-clash.yaml"))
        export_singbox_json(res_proxies, os.path.join(OUTPUT_DIR, "residential-singbox.json"))
    else:
        for f in ["residential-clash.yaml", "residential-singbox.json"]:
            p = os.path.join(OUTPUT_DIR, f)
            if os.path.exists(p): os.remove(p)

    # 3. 按国家分类【非家宽/机房】
    shutil.rmtree(COUNTRY_DIR, ignore_errors=True)
    os.makedirs(COUNTRY_DIR, exist_ok=True)
    by_cc = {}
    for n in non_residential_nodes:
        by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in by_cc.items():
        c_links, c_proxies = format_node_group(n_list)
        with open(os.path.join(COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(c_links).encode()).decode())
        export_clash_yaml(c_proxies, os.path.join(COUNTRY_DIR, f"clash-{cc}.yaml"))
        export_singbox_json(c_proxies, os.path.join(COUNTRY_DIR, f"singbox-{cc}.json"))

    # 4. 按国家分类【真家宽】
    shutil.rmtree(RESIDENTIAL_COUNTRY_DIR, ignore_errors=True)
    os.makedirs(RESIDENTIAL_COUNTRY_DIR, exist_ok=True)
    res_by_cc = {}
    for n in residential_nodes:
        res_by_cc.setdefault(n["country"], []).append(n)

    for cc, n_list in res_by_cc.items():
        cr_links, cr_proxies = format_node_group(n_list, res_tag_force=True)
        with open(os.path.join(RESIDENTIAL_COUNTRY_DIR, f"{cc}.txt"), "w", encoding="utf-8") as f:
            f.write(base64.b64encode("\n".join(cr_links).encode()).decode())
        export_clash_yaml(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"clash-{cc}.yaml"))
        export_singbox_json(cr_proxies, os.path.join(RESIDENTIAL_COUNTRY_DIR, f"singbox-{cc}.json"))

    print(f"[*] 导出完毕！全量真活: {len(all_links)} | 家宽真活: {len(res_links)}")
    return len(all_links), len(res_links)

def update_readme():
    repo_name = os.environ.get("GITHUB_REPOSITORY", "hezhanleiok/freesub").strip()
    cache_bust = int(time.time())
    
    def count_file(path):
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                c = f.read().strip()
                if not c:
                    return 0
                decoded = base64.b64decode(c).decode("utf-8", errors="ignore")
                return len([line for line in decoded.splitlines() if line.strip()])
        except Exception:
            return 0

    total_count = count_file(os.path.join(OUTPUT_DIR, "v2ray.txt"))
    res_count = count_file(os.path.join(OUTPUT_DIR, "residential.txt"))

    res_counts = {}
    if os.path.exists(RESIDENTIAL_COUNTRY_DIR):
        for fn in os.listdir(RESIDENTIAL_COUNTRY_DIR):
            if fn.endswith(".txt"):
                cc = fn[:-4]
                cnt = count_file(os.path.join(RESIDENTIAL_COUNTRY_DIR, fn))
                if cnt > 0:
                    res_counts[cc] = cnt

    normal_counts = {}
    if os.path.exists(COUNTRY_DIR):
        for fn in os.listdir(COUNTRY_DIR):
            if fn.endswith(".txt"):
                cc = fn[:-4]
                cnt = count_file(os.path.join(COUNTRY_DIR, fn))
                if cnt > 0:
                    normal_counts[cc] = cnt

    clash_cdn_url = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/clash.yaml?v={cache_bust}"
    clash_raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/output/clash.yaml"
    v2_cdn_url = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/v2ray.txt?v={cache_bust}"
    v2_raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/output/v2ray.txt"
    sb_cdn_url = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/singbox.json?v={cache_bust}"
    sb_raw_url = f"https://raw.githubusercontent.com/{repo_name}/main/output/singbox.json"

    res_rows = []
    for cc in sorted(res_counts.keys(), key=lambda x: res_counts[x], reverse=True):
        flag = get_country_flag(cc)
        name = COUNTRY_NAMES.get(cc, cc)
        cnt = res_counts[cc]
        v2_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/{cc}.txt?v={cache_bust}"
        v2_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/clash-{cc}.yaml?v={cache_bust}"
        clash_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/clash-{cc}.yaml"
        sb_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/residential-by-country/singbox-{cc}.json?v={cache_bust}"
        sb_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/residential-by-country/singbox-{cc}.json"

        col_v2 = f"[CDN 直链]({v2_cdn}) · [Raw 直链]({v2_raw})"
        col_clash = f"[CDN 直链]({clash_cdn}) · [Raw 直链]({clash_raw})"
        col_sb = f"[CDN 直链]({sb_cdn}) · [Raw 直链]({sb_raw})"
        res_rows.append(f"| {flag} {name} | {cnt} | {col_v2} | {col_clash} | {col_sb} |")
    res_table_str = "\n".join(res_rows) if res_rows else "| 暂无可用家宽节点 | 0 | - | - | - |"

    normal_rows = []
    for cc in sorted(normal_counts.keys(), key=lambda x: normal_counts[x], reverse=True):
        flag = get_country_flag(cc)
        name = COUNTRY_NAMES.get(cc, cc)
        cnt = normal_counts[cc]
        v2_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/{cc}.txt?v={cache_bust}"
        v2_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/{cc}.txt"
        clash_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/clash-{cc}.yaml?v={cache_bust}"
        clash_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/clash-{cc}.yaml"
        sb_cdn = f"https://cdn.jsdelivr.net/gh/{repo_name}@main/output/by-country/singbox-{cc}.json?v={cache_bust}"
        sb_raw = f"https://raw.githubusercontent.com/{repo_name}/main/output/by-country/singbox-{cc}.json"

        col_v2 = f"[CDN 直链]({v2_cdn}) · [Raw 直链]({v2_raw})"
        col_clash = f"[CDN 直链]({clash_cdn}) · [Raw 直链]({clash_raw})"
        col_sb = f"[CDN 直链]({sb_cdn}) · [Raw 直链]({sb_raw})"
        normal_rows.append(f"| {flag} {name} | {cnt} | {col_v2} | {col_clash} | {col_sb} |")
    normal_table_str = "\n".join(normal_rows) if normal_rows else "| 暂无可用节点 | 0 | - | - | - |"

    worker_code = """```javascript
export default {
  async fetch(request, env) {
    // 安全提示：令牌通过 Cloudflare Worker 的加密环境变量注入（Settings ->
    // Variables and Secrets -> 添加 GITHUB_TOKEN），绝不写死在源码里。
    // 公开仓库完全不需要令牌，留空即可。
    const GITHUB_TOKEN = env.GITHUB_TOKEN || "";
    const OWNER = "hezhanleiok";
    const REPO = "freesub";
    const BRANCH = "main";

    const url = new URL(request.url);
    const filePath = "output" + url.pathname;
    const ghUrl = "https://raw.githubusercontent.com/" + OWNER + "/" + REPO + "/" + BRANCH + "/" + filePath;

    const headers = { "User-Agent": "Cloudflare-Worker" };
    if (GITHUB_TOKEN) headers["Authorization"] = "token " + GITHUB_TOKEN;

    const res = await fetch(ghUrl, { headers });

    if (!res.ok) {
      return new Response("Not Found", { status: 404 });
    }

    return new Response(await res.text(), {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache"
      }
    });
  }
}
```"""

    readme_content = f"""# 🚀 免费节点自动测活订阅池 (含真实家宽/住宅IP甄选)

> 👤 **定制规范命名**: 所有订阅节点均重命名为 `国旗 地区 序号 (家宽) - xiaohe`  
> ⚡ **真实可用保障**: 所有节点由 `Xray-core` 建立实际代理隧道并完成真实 HTTPS 双向传输握手，拒绝虚假通畅与死节点。无论是通过免翻 CDN 直链还是官方原生 Raw 直链拉取，节点命名格式完全一致。

---

## 📌 全部节点总订阅链接

| <div style="min-width:180px;">客户端 / 格式类型</div> | <div style="min-width:80px;">节点总数</div> | 免翻 CDN 订阅直链 (国内直连) | 官方原生 Raw 直链 (开启代理) |
| :--- | :---: | :--- | :--- |
| 🚀 **Clash (YAML 格式)** | `{total_count}` | [🚀 免翻 CDN 直链]({clash_cdn_url}) | [🌐 官方 Raw 直链]({clash_raw_url}) |
| ⚡ **V2RayN (Base64 格式)** | `{total_count}` | [⚡ 免翻 CDN 直链]({v2_cdn_url}) | [🌐 官方 Raw 直链]({v2_raw_url}) |
| 📦 **sing-box (JSON 格式)** | `{total_count}` | [📦 免翻 CDN 直链]({sb_cdn_url}) | [🌐 官方 Raw 直链]({sb_raw_url}) |

---

## 🏠 按照家宽分类节点订阅 (住宅 IP 专区)
> 经 MaxMind ASN 数据库与核心运营商白名单严格探测，排除所有云主机/数据中心及 CDN 任播，保留真实民用宽带。

| 家宽地区 | 节点数 | V2RayN 专属订阅 | Clash 专属订阅 | sing-box 专属订阅 |
| :--- | :---: | :---: | :---: | :---: |
{res_table_str}

---

## 🗺️ 按照国家分类节点订阅 (非家宽/数据中心节点)

| 地区/国家 | 节点数 | V2RayN 专属订阅 | Clash 专属订阅 | sing-box 专属订阅 |
| :--- | :---: | :---: | :---: | :---: |
{normal_table_str}

---

## 🔒 私有仓库（Private）无感免翻订阅方案 (基于 Cloudflare Workers)

> 如果你希望将本 GitHub 仓库设置为 **Private (私有仓库)** 保护节点资产，外部客户端无法直接拉取原生 Raw 或公共 CDN 链接，可以通过以下 Cloudflare Worker 搭建轻量级私密网关反代：

### 1. 获取 GitHub 永久个人令牌 (PAT)
1. 进入 GitHub -> **Settings** -> **Developer Settings** -> **Personal access tokens (classic)**。
2. 点击 **Generate new token (classic)**，勾选 `repo` 权限，有效期设为 `No expiration`（永不过期）。
3. 复制保存生成的以 `ghp_` 开头的 Token。

### 2. 部署 Cloudflare Worker
登录 Cloudflare Dashboard，创建一个新的 Worker，复制以下脚本粘贴并部署：

{worker_code}

### 3. 私有订阅链接映射方式
部署后 Worker 会分配一个专属域名（例如 `my-sub.yourname.workers.dev`），你的客户端可以直接无感订阅：
* **总 V2RayN 订阅**: `https://你的域名.workers.dev/v2ray.txt`
* **总 Clash 订阅**: `https://你的域名.workers.dev/clash.yaml`
* **总 sing-box 订阅**: `https://你的域名.workers.dev/singbox.json`
* **台湾家宽 V2RayN**: `https://你的域名.workers.dev/residential-by-country/TW.txt`
* **香港家宽 Clash**: `https://你的域名.workers.dev/residential-by-country/clash-HK.yaml`
* **日本家宽 sing-box**: `https://你的域名.workers.dev/residential-by-country/singbox-JP.json`

---

## ⭐ 项目热度

[![Star History Chart](https://api.star-history.com/svg?repos={repo_name}&type=Date)](https://star-history.com/#{repo_name}&Date)

---

## ⚠️ 风险提示（务必阅读）

1. **免费节点 ≠ 安全节点**：这些节点来自公共订阅池，运营者不可信，理论上可以记录你的全部流量。
   **严禁**用它们登录网银、邮箱、公司系统、社交账号等任何含敏感凭据的场景。
2. **测活语义**：测活验证的是"海外服务器经该节点访问 Google 204 通畅"，不代表国内网络环境下的
   实际速度与稳定性，晚高峰可能大幅劣化。
3. **家宽/住宅 IP 判定**：基于 ASN + 反解析关键词的启发式判断，可能误判；"住宅 IP"不代表"干净 IP"。
4. 使用即视为接受上述风险，请自行评估。

---

## 🛠️ 项目使用说明
1. **自动更新机制**：GitHub Actions 每 6 小时全自动运行并刷新上述全部订阅与数据。
2. **多客户端兼容**：
   - **Clash / Clash Verge / Mihomo Party**：直接复制上方表格中的 **Clash 专属订阅** 链接。
   - **v2rayN / v2rayNG**：直接复制上方表格中的 **V2RayN 专属订阅** 链接。
   - **sing-box**：直接使用上方 **sing-box 专属订阅** 链接。
"""
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"[+] README.md 实时动态表格更新完毕！真实总节点: {total_count}, 真实家宽: {res_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="免费节点抓取 / 真连接测活 / 分类出库")
    parser.add_argument("--dry-run", action="store_true",
                        help="只抓订阅源并解析，不做测活、不写 output（换源后快速自检用）")
    parser.add_argument("--suffix", default=NODE_SUFFIX,
                        help=f"节点名后缀，默认 {NODE_SUFFIX}")
    args = parser.parse_args()
    NODE_SUFFIX = args.suffix

    raw_nodes = fetch_raw_nodes()

    candidates = []
    proto_stat = {}
    for raw in raw_nodes:
        outbound, server, port, proto = parse_node_to_xray_outbound(raw)
        if outbound and server and port:
            candidates.append((raw, server, port, proto))
            proto_stat[proto] = proto_stat.get(proto, 0) + 1

    print(f"[*] 格式合规候选节点数: {len(candidates)} | 协议分布: {proto_stat}")

    if args.dry_run:
        print("[*] --dry-run 模式：只做抓源与解析自检，不测活、不出库。")
        sys.exit(0)

    setup_environment()
    alive_nodes = run_real_delay_test_xray(candidates)
    verified = classify_and_filter(alive_nodes)
    export_subscriptions(verified)
    update_readme()
