import re
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://ip.v2too.top/"
OUTPUT = "ipv4.txt"

TABS = [
    ("ct", "中国电信", "电信"),
    ("cm", "中国移动", "移动"),
    ("cu", "中国联通", "联通"),
]

IP_RE = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"


def is_valid_ip(ip):
    try:
        parts = [int(x) for x in ip.split(".")]
        if len(parts) != 4:
            return False
        if any(x < 0 or x > 255 for x in parts):
            return False

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


def get_delay(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*ms", text, re.I)
    return float(m.group(1)) if m else 0.0


def get_speed(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*MB\s*/\s*s", text, re.I)
    return float(m.group(1)) if m else 0.0


def auto_scroll(page):
    for _ in range(8):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(700)


def get_region_from_block(block, ip):
    lines = [x.strip() for x in block.splitlines() if x.strip()]

    for index, line in enumerate(lines):
        if line == ip:
            for next_line in lines[index + 1:index + 6]:
                if next_line.startswith("#"):
                    continue
                if re.search(IP_RE, next_line):
                    continue
                if next_line in ["下载速度", "网络延迟"]:
                    continue
                if "MB/s" in next_line:
                    continue
                if "ms" in next_line:
                    continue

                return next_line

    return "未知"


def extract_from_text(text, isp):
    items = []
    seen = set()

    blocks = re.split(r"(?m)^\s*#\d+\s*$", text)

    for block in blocks:
        ip_match = re.search(IP_RE, block)

        if not ip_match:
            continue

        ip = ip_match.group(0)

        if not is_valid_ip(ip):
            continue

        if ip in seen:
            continue

        seen.add(ip)

        region = get_region_from_block(block, ip)
        delay = get_delay(block)
        speed = get_speed(block)

        items.append({
            "ip": ip,
            "region": region,
            "isp": isp,
            "delay": delay,
            "speed": speed,
        })

    return items


def click_tab(page, tab_id, tab_name):
    btn = page.locator(f'button[data-id="{tab_id}"]')

    if btn.count() > 0:
        btn.first.click(timeout=10000)
        return

    page.get_by_role("button", name=tab_name).click(timeout=10000)


def main():
    all_items = []
    debug_texts = []

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

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        for tab_id, tab_name, isp in TABS:
            print(f"开始提取：{isp}")

            try:
                click_tab(page, tab_id, tab_name)
                page.wait_for_timeout(8000)
                auto_scroll(page)

                body_text = page.locator("body").inner_text(timeout=10000)

                debug_texts.append(
                    f"\n\n===== {isp} 页面文本 =====\n{body_text}"
                )

                items = extract_from_text(body_text, isp)

                print(f"{isp} 页面文本提取到 {len(items)} 条")

                all_items.extend(items)

            except Exception as e:
                print(f"{isp} 提取失败：{e}")

        try:
            page.screenshot(path="debug_screenshot.png", full_page=True)
        except Exception:
            pass

        browser.close()

    Path("debug_text.txt").write_text("\n".join(debug_texts), encoding="utf-8")

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
        print("请查看 debug_text.txt 和 debug_screenshot.png。")


if __name__ == "__main__":
    main()