#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# 用途：把 Shadowsocks 订阅（ss:// 链接或 base64）转换成 mihomo/clash YAML
#
# 用法示例：
#   python ss_sub_to_mihomo.py "https://villa.parkson-market.org/api/v1/trails/bolster?token=XXXX" > config.yaml
#
#   或者：
#   python ss_sub_to_mihomo.py sub.txt > config.yaml
#
#   sub.txt 里是你已经 wget 下来的订阅内容（可以是 base64 也可以是明文 ss:// 列表）

import sys
import base64
import urllib.parse
import urllib.request


def fetch_content(source: str) -> str:
    """从 URL 或 本地文件 读取内容"""
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source) as resp:
            data = resp.read()
        return data.decode("utf-8", errors="ignore")
    else:
        with open(source, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def maybe_base64_decode(text: str) -> str:
    """如果内容里没看到 ss://，尝试当做 base64 解码一次"""
    if "ss://" in text:
        return text

    raw = text.strip()
    # 补齐 base64 padding
    pad_len = (-len(raw)) % 4
    raw_padded = raw + ("=" * pad_len)
    try:
        decoded = base64.b64decode(raw_padded)
        return decoded.decode("utf-8", errors="ignore")
    except Exception:
        # 解不了就原样返回
        return text


def parse_ss_link(link: str, idx: int):
    """解析单条 ss:// 链接，返回一个 proxy dict，解析失败则返回 None"""
    link = link.strip()
    if not link:
        return None
    if not link.startswith("ss://"):
        return None

    # 处理可能存在的换行 / 空格
    # 确保是标准 URL 格式
    url = link

    # 用 urlparse 分解
    parsed = urllib.parse.urlparse(url)

    # 可能有两种格式：
    #   1) ss://base64(method:password)@host:port?plugin=...
    #   2) ss://base64(method:password@host:port)?plugin=...
    netloc = parsed.netloc
    fragment = urllib.parse.unquote(parsed.fragment) if parsed.fragment else f"proxy-{idx}"

    # 如果 netloc 为空，有可能整个 base64 在 path 里
    if not netloc and parsed.path:
        # ss:// + base64 部分
        b64_part = parsed.path
        # 去掉可能开头的 '//'
        if b64_part.startswith("//"):
            b64_part = b64_part[2:]
        # 补齐 padding
        pad_len = (-len(b64_part)) % 4
        b64_padded = b64_part + ("=" * pad_len)
        try:
            decoded = base64.b64decode(b64_padded).decode("utf-8", errors="ignore")
        except Exception:
            return None
        # decoded 形如 method:password@host:port
        # 再用一次 urlparse
        if not decoded.startswith("//"):
            decoded = "//" + decoded
        parsed2 = urllib.parse.urlparse("ss:" + decoded)
        netloc = parsed2.netloc
    # 此时 netloc 应该形如  "base64(method:pass)@host:port"
    if "@" not in netloc:
        return None

    userinfo, hostport = netloc.split("@", 1)
    # 解密 userinfo （method:password）
    pad_len = (-len(userinfo)) % 4
    userinfo_padded = userinfo + ("=" * pad_len)
    try:
        method_pass = base64.b64decode(userinfo_padded).decode("utf-8", errors="ignore")
    except Exception:
        return None

    if ":" not in method_pass:
        return None
    method, password = method_pass.split(":", 1)

    # 解析 host:port
    if ":" not in hostport:
        return None
    host, port_str = hostport.split(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        return None

    proxy = {
        "name": fragment,
        "type": "ss",
        "server": host,
        "port": port,
        "cipher": method,
        "password": password,
    }

    # 处理 plugin
    if parsed.query:
        q = urllib.parse.parse_qs(parsed.query)
        plugin_raw = q.get("plugin", [""])[0]
        if plugin_raw:
            plugin_str = urllib.parse.unquote(plugin_raw)
            # 例如： "simple-obfs;obfs=http;obfs-host=xxx"
            parts = plugin_str.split(";")
            plugin_name = parts[0]
            # 目前主要兼容 simple-obfs -> mihomo 的 obfs 插件
            if plugin_name in ("simple-obfs", "obfs"):
                opts = {}
                for item in parts[1:]:
                    if "=" in item:
                        k, v = item.split("=", 1)
                        opts[k.strip()] = v.strip()
                # 映射到 mihomo 的写法
                mode = opts.get("obfs", "http")
                host_hdr = opts.get("obfs-host", "")
                proxy["plugin"] = "obfs"
                proxy["plugin-opts"] = {
                    "mode": mode,
                    "host": host_hdr,
                }
            else:
                # 其他插件，暂时原样带上 plugin 字段（mihomo 不一定支持）
                proxy["plugin"] = plugin_name

    return proxy


def main():
    if len(sys.argv) < 2:
        print("用法: python ss_sub_to_mihomo.py <订阅URL或本地文件> > config.yaml")
        sys.exit(1)

    source = sys.argv[1]
    text = fetch_content(source)
    text = maybe_base64_decode(text)

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    proxies = []
    for idx, line in enumerate(lines, 1):
        if not line.startswith("ss://"):
            continue
        p = parse_ss_link(line, idx)
        if p:
            proxies.append(p)

    if not proxies:
        print("# 没有解析到任何 ss:// 节点，请检查订阅内容")
        sys.exit(1)

    # 开始输出 mihomo YAML
    print("port: 7890")
    print("socks-port: 7891")
    print("allow-lan: true")
    print("mode: Rule")
    print("log-level: info")
    print("external-controller: 127.0.0.1:9090")
    print()
    print("proxies:")
    for p in proxies:
        print(f'  - name: "{p["name"]}"')
        print("    type: ss")
        print(f'    server: {p["server"]}')
        print(f'    port: {p["port"]}')
        print(f'    cipher: {p["cipher"]}')
        print(f'    password: "{p["password"]}"')
        if "plugin" in p:
            if p["plugin"] == "obfs":
                opts = p.get("plugin-opts", {})
                mode = opts.get("mode", "http")
                host_hdr = opts.get("host", "")
                print("    plugin: obfs")
                print("    plugin-opts:")
                print(f"      mode: {mode}")
                if host_hdr:
                    print(f"      host: {host_hdr}")
            else:
                # 其他插件，简单带上名字
                print(f'    plugin: "{p["plugin"]}"')
        print()

    print("proxy-groups:")
    print('  - name: "auto-select"')
    print("    type: select")
    print("    proxies:")
    for p in proxies:
        print(f'      - "{p["name"]}"')
    print("      - DIRECT")
    print()
    print("rules:")
    print("  - MATCH,auto-select")


if __name__ == "__main__":
    main()
