import re
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://ip.v2too.top/"
OUTPUT = "ipv4.txt"

TABS = [
    ("中国电信", "电信"),
    ("中国移动", "移动"),
    ("中国联通", "联通"),
]

REGIONS = [
    "东京", "香港", "新加坡", "首尔", "大阪", "洛杉矶",
    "美国", "日本", "韩国", "台湾", "台北",
    "德国", "英国", "法国", "加拿大", "荷兰", "俄罗斯",
    "圣何塞", "西雅图", "法兰克福", "伦敦", "巴黎",
    "曼谷", "越南", "印度", "孟买", "悉尼"
]

IP_RE = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"


def is_valid_ip(ip):
    try:
        parts = [int(x) for x in ip.split(".")]
        if len(parts) != 4:
            return False
        if any(x < 0 or x > 255 for x in parts):
            return False

        # 排除本地/内网地址
        if parts[0] == 10:
            return False
        if parts[0] == 127:
            return False
        if parts[0] == 192 and parts[1] == 168:
            return False
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            return False

        return True
    except Exception:
        return False


def get_region(text):
    for region in REGIONS:
        if region in text:
            return region
    return "未知"


def get_isp(text, default_isp):
    if "电信" in text:
        return "电信"
    if "移动" in text:
        return "移动"
    if "联通" in text:
        return "联通"
    return default_isp


def get_delay(text):
    patterns = [
        r"(\d+(?:\.\d+)?)\s*ms",
        r"延迟[^\d]*(\d+(?:\.\d+)?)",
        r"delay[^\d]*(\d+(?:\.\d+)?)",
        r"latency[^\d]*(\d+(?:\.\d+)?)",
        r"ping[^\d]*(\d+(?:\.\d+)?)",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return float(m.group(1))

    return 0.0


def get_speed(text):
    patterns = [
        r"(\d+(?:\.\d+)?)\s*MB\s*/\s*s",
        r"速度[^\d]*(\d+(?:\.\d+)?)",
        r"speed[^\d]*(\d+(?:\.\d+)?)",
        r"download[^\d]*(\d+(?:\.\d+)?)",
    ]

    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return float(m.group(1))

    return 0.0


def auto_scroll(page):
    for _ in range(8):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(800)


def extract_from_text(text, default_isp):
    items = []

    for m in re.finditer(IP_RE, text):
        ip = m.group(0)

        if not is_valid_ip(ip):
            continue

        start = max(0, m.start() - 500)
        end = min(len(text), m.end() + 1000)
        around = text[start:end]

        item = {
            "ip": ip,
            "region": get_region(around),
            "isp": get_isp(around, default_isp),
            "delay": get_delay(around),
            "speed": get_speed(around),
        }

        items.append(item)

    return items


def flatten_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def walk_json(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_json(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from walk_json(x)


def extract_from_json_text(text, default_isp):
    items = []

    try:
        data = json.loads(text)
    except Exception:
        return items

    for obj in walk_json(data):
        blob = flatten_json(obj)

        if not re.search(IP_RE, blob):
            continue

        items.extend(extract_from_text(blob, default_isp))

    return items


def main():
    all_items = []
    network_logs = []
    page_text_logs = []
    response_bodies = []

    current_isp = "电信"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        page = browser.new_page(
            viewport={"width": 390, "height": 1600},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Mobile) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        )

        def handle_response(response):
            try:
                url = response.url
                headers = response.headers
                content_type = headers.get("content-type", "")

                network_logs.append(f"[{response.status}] {content_type} {url}")

                if any(x in content_type for x in ["json", "text", "javascript"]):
                    body = response.text()

                    if len(body) < 2_000_000:
                        response_bodies.append((url, body, current_isp))

            except Exception:
                pass

        page.on("response", handle_response)

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        for tab_text, isp in TABS:
            current_isp = isp
            print(f"开始提取：{isp}")

            try:
                page.get_by_text(tab_text, exact=False).click(timeout=10000)
            except Exception as e:
                print(f"点击 {tab_text} 失败：{e}")

            page.wait_for_timeout(8000)
            auto_scroll(page)

            try:
                body_text = page.locator("body").inner_text(timeout=10000)
                page_text_logs.append(f"\n\n===== {isp} 页面文本 =====\n{body_text[:5000]}")

                text_items = extract_from_text(body_text, isp)
                all_items.extend(text_items)

                print(f"{isp} 页面文本提取到 {len(text_items)} 条")

            except Exception as e:
                print(f"{isp} 页面文本读取失败：{e}")

        page.screenshot(path="debug_screenshot.png", full_page=True)
        browser.close()

    # 从接口返回内容里提取
    for url, body, isp in response_bodies:
        json_items = extract_from_json_text(body, isp)
        text_items = extract_from_text(body, isp)

        found = json_items if json_items else text_items

        if found:
            print(f"接口发现 IP：{url}，数量 {len(found)}")
            all_items.extend(found)

    # 保存调试文件
    Path("debug_network.txt").write_text("\n".join(network_logs), encoding="utf-8")
    Path("debug_text.txt").write_text("\n".join(page_text_logs), encoding="utf-8")

    # 去重：同一个 IP 保留速度最高的
    best = {}

    for item in all_items:
        ip = item["ip"]

        if ip not in best:
            best[ip] = item
        else:
            old = best[ip]

            if item["speed"] > old["speed"]:
                best[ip] = item

    result = sorted(
        best.values(),
        key=lambda x: (-x["speed"], x["delay"])
    )

    lines = []

for i in result:
    line = f'{i["ip"]}:443#{i["region"]}'
    lines.append(line)

if lines:
    Path(OUTPUT).write_text("\n".join(lines), encoding="utf-8")
    print(f"成功生成 {OUTPUT}，共 {len(lines)} 条")
    print("\n".join(lines[:20]))
else:
    print("没有提取到 IP，没有覆盖 ipv4.txt。")
    print("请查看 debug_network.txt、debug_text.txt、debug_screenshot.png。")

if lines:
    Path(OUTPUT).write_text("\n".join(lines), encoding="utf-8")
    print(f"成功生成 {OUTPUT}，共 {len(lines)} 条")
    print("\n".join(lines[:20]))
else:
    print("没有提取到 IP，没有覆盖 ipv4.txt。")
    print("请查看 debug_network.txt、debug_text.txt、debug_screenshot.png。")

    if lines:
        Path(OUTPUT).write_text("\n".join(lines), encoding="utf-8")
        print(f"成功生成 {OUTPUT}，共 {len(lines)} 条")
        print("\n".join(lines[:20]))
    else:
        print("没有提取到 IP，没有覆盖 ipv4.txt。")
        print("请查看 debug_network.txt、debug_text.txt、debug_screenshot.png。")


if __name__ == "__main__":
    main()