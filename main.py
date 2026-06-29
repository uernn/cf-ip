import re
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://ip.v2too.top/"
OUTPUT = "ipv4.txt"

ISPS = {
    "中国电信": "电信",
    "中国移动": "移动",
    "中国联通": "联通",
}

REGIONS = [
    "东京", "香港", "新加坡", "首尔", "大阪", "洛杉矶",
    "美国", "日本", "韩国", "台湾", "德国", "英国",
    "法国", "加拿大", "荷兰", "俄罗斯"
]

def get_delay(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*ms", text, re.I)
    return float(m.group(1)) if m else 0

def get_speed(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*MB/s", text, re.I)
    return float(m.group(1)) if m else 0

def get_region(text):
    for r in REGIONS:
        if r in text:
            return r
    return "未知"

def extract_items(page, isp_name):
    items = []
    text = page.inner_text("body")

    ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ips = re.findall(ip_pattern, text)

    blocks = re.split(ip_pattern, text)
    seen = set()

    for index, ip in enumerate(ips):
        if ip in seen:
            continue
        seen.add(ip)

        around = ""

        if index < len(blocks):
            around += blocks[index]

        if index + 1 < len(blocks):
            around += blocks[index + 1]

        region = get_region(around)
        delay = get_delay(around)
        speed = get_speed(around)

        items.append({
            "ip": ip,
            "region": region,
            "isp": isp_name,
            "delay": delay,
            "speed": speed,
        })

    return items

def main():
    all_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 390, "height": 1200},
            user_agent="Mozilla/5.0"
        )

        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(8000)

        for tab_text, isp_name in ISPS.items():
            try:
                page.get_by_text(tab_text, exact=False).click(timeout=5000)
                page.wait_for_timeout(3000)

                items = extract_items(page, isp_name)
                all_items.extend(items)

                print(f"{isp_name} 提取到 {len(items)} 条")

            except Exception as e:
                print(f"{isp_name} 提取失败：{e}")

        browser.close()

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
        line = (
            f'{i["ip"]}:443#'
            f'{i["region"]} {i["isp"]}优选'
            f'[{int(i["delay"])}ms {i["speed"]:.2f}MB/s]'
        )
        lines.append(line)

    Path(OUTPUT).write_text("\n".join(lines), encoding="utf-8")

    print(f"成功生成 {OUTPUT}，共 {len(lines)} 条")

if __name__ == "__main__":
    main()