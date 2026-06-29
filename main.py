import re
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
    "圣何塞", "西雅图", "法兰克福", "伦敦", "巴黎"
]

IP_RE = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"


def get_region(text):
    for region in REGIONS:
        if region in text:
            return region
    return "未知"


def get_delay(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*ms", text, re.I)
    if m:
        return float(m.group(1))
    return 0.0


def get_speed(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*MB\s*/\s*s", text, re.I)
    if m:
        return float(m.group(1))
    return 0.0


def auto_scroll(page):
    last_height = 0

    for _ in range(10):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(800)

        height = page.evaluate("document.body.scrollHeight")

        if height == last_height:
            break

        last_height = height


def extract_from_text(text, isp):
    items = []
    seen = set()

    for m in re.finditer(IP_RE, text):
        ip = m.group(0)

        if ip in seen:
            continue

        seen.add(ip)

        start = max(0, m.start() - 300)
        end = min(len(text), m.end() + 800)
        around = text[start:end]

        region = get_region(around)
        delay = get_delay(around)
        speed = get_speed(around)

        items.append({
            "ip": ip,
            "region": region,
            "isp": isp,
            "delay": delay,
            "speed": speed,
        })

    return items


def main():
    all_items = []
    debug_texts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        page = browser.new_page(
            viewport={"width": 390, "height": 1600},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Mobile Safari/537.36"
            )
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        for tab_text, isp in TABS:
            print(f"开始提取：{isp}")

            try:
                page.get_by_text(tab_text, exact=False).click(timeout=10000)
                page.wait_for_timeout(5000)

                auto_scroll(page)

                body_text = page.locator("body").inner_text(timeout=10000)
                debug_texts.append(f"\n\n===== {isp} 页面文本 =====\n{body_text[:3000]}")

                items = extract_from_text(body_text, isp)

                print(f"{isp} 提取到 {len(items)} 条")

                all_items.extend(items)

            except Exception as e:
                print(f"{isp} 提取失败：{e}")

        Path("debug_text.txt").write_text("\n".join(debug_texts), encoding="utf-8")

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

    if not lines:
        raise RuntimeError(
            "没有提取到任何 IP，已停止写入 ipv4.txt，避免生成空文件。请查看 debug_text.txt 或 Actions 日志。"
        )

    Path(OUTPUT).write_text("\n".join(lines), encoding="utf-8")

    print(f"成功生成 {OUTPUT}，共 {len(lines)} 条")
    print("\n".join(lines[:10]))


if __name__ == "__main__":
    main()