import os, sys
sys.path.insert(0, r"E:\code\freesub-improved\scripts")
os.chdir(r"E:\code\freesub-improved")
import main as m

fails = []

def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# 1. hy2 解析
o, srv, port, proto = m.parse_node_to_xray_outbound("hysteria2://passwd123@example.com:443?sni=cdn.example.com#Test")
check("hy2 parse", o is not None and proto == "hysteria2" and port == 443, str((o, srv, port, proto)))

# 2. vless reality flow
o2, s2, p2, pr2 = m.parse_node_to_xray_outbound(
    "vless://uuid-1234@1.2.3.4:443?security=reality&pbk=pubkeyAB&sid=abcd&sni=www.apple.com&flow=xtls-rprx-vision&fp=chrome#test")
flow = o2["settings"]["vnext"][0]["users"][0].get("flow") if o2 else None
check("vless reality flow 保留", flow == "xtls-rprx-vision", str(flow))

# 3. clash reality 补 short-id + flow（原版丢了 shortId，reality 节点在 Clash 里连不上）
c = m.convert_to_clash_dict(
    "vless://uuid-1234@1.2.3.4:443?security=reality&pbk=pubkeyAB&sid=abcd&sni=www.apple.com&flow=xtls-rprx-vision#test", "temp")
check("clash reality short-id", c is not None and c.get("reality-opts", {}).get("short-id") == "abcd", str(c))
check("clash reality flow", c.get("flow") == "xtls-rprx-vision", str(c))

# 4. rename + 自定义后缀
renamed = m.rename_node_link("vless://uuid-1234@1.2.3.4:443?security=none#old", "🇯🇵 日本 (Japan) 01 - myname")
check("rename_node_link 后缀", renamed.endswith("#🇯🇵 日本 (Japan) 01 - myname"), renamed)

# 5. format_node_group 使用 NODE_SUFFIX
nodes = [{"country": "JP", "is_residential": False,
          "clash_proxy": {"name": "x", "type": "vless", "server": "a", "port": 1, "uuid": "u"},
          "link": "vless://uuid-1234@1.2.3.4:443?security=none"}]
links, proxies = m.format_node_group(nodes)
check("format_node_group 后缀", links[0].endswith("#🇯🇵 日本 (Japan) 01 - xiaohe"), links[0])

# 6. sort_by_delay
srt = m.sort_by_delay([{"delay": 900}, {"delay": 100}, {"delay": 500}])
check("sort_by_delay", [x["delay"] for x in srt] == [100, 500, 900])

# 7. 版本动态获取（真实网络）
xv = m.get_latest_release_version("XTLS/Xray-core", m.XRAY_FALLBACK_VERSION)
sv = m.get_latest_release_version("SagerNet/sing-box", m.SINGBOX_FALLBACK_VERSION)
check("Xray 版本动态获取", xv == "26.3.27", xv)
check("sing-box 版本动态获取", sv == "1.14.0", sv)

# 8. README Worker 代码修复 + 风险提示
m.update_readme()
readme = open("README.md", encoding="utf-8").read()
bad_md = "[https://raw.githubusercontent.com/](https://raw.githubusercontent.com/)" in readme
good_url = '"https://raw.githubusercontent.com/" + OWNER' in readme
check("Worker URL bug 已修复", (not bad_md) and good_url)
check("README 有风险提示", "风险提示" in readme)
check("README 有 Secrets 说明", "env.GITHUB_TOKEN" in readme)

# 9. 国家名覆盖：检查现有 output 里所有国家都在中英对照表里
import glob
present = {os.path.basename(p)[:-4] for p in glob.glob("output/by-country/*.txt")}
present |= {os.path.basename(p)[:-4] for p in glob.glob("output/residential-by-country/*.txt")}
missing = sorted(present - set(m.COUNTRY_NAMES))
check("国家名表覆盖全部出库国家", not missing, f"缺: {missing}")

print()
print("FAILURES:", fails if fails else "无，全部通过")
