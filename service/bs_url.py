# service/bs_url.py
import re, time, csv
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# URL 입력 필요
BASE = "http://m.garampos.co.kr"
LIST_TMPL = "http://m.garampos.co.kr/bbs_shop/list.htm?board_code=rwdboard&page={page}"

UA = {"User-Agent": "Mozilla/5.0"}
TITLE_TAIL_RE = re.compile(r"\s+(file|photo)\s*$", re.IGNORECASE)

def clean_title(s: str) -> str:
    return TITLE_TAIL_RE.sub("", s.strip())

def parse_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    # 규칙: read.htm 링크가 들어있는 <a>를 기준으로 tr을 잡는다
    for a in soup.select('a[href*="read.htm"]'):
        tr = a.find_parent("tr")
        if not tr:
            continue
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]

        # 안전하게 번호와 작성자만 탐색
        num = None
        author = ""
        if tds:
            # 번호는 정수만 추출
            for tok in tds[0].split():
                if tok.isdigit():
                    num = int(tok)
                    break
            # 작성자는 뒤쪽 셀 중 한 곳에 있음
            for td in reversed(tds[1:]):
                # 날짜/조회수 등 숫자 위주 값 건너뛰기
                if re.fullmatch(r"[\d\-\.:/]+|^\d+$", td):
                    continue
                author = td
                break

        title = clean_title(a.get_text(" ", strip=True))
        href = urljoin(BASE, a.get("href"))

        if num is not None:
            rows.append({"번호": num, "제목": title, "URL": href})
    return rows

def crawl(max_pages=20, delay=0.6):
    seen = {}
    for p in range(1, max_pages + 1):
        url = LIST_TMPL.format(page=p)
        r = requests.get(url, headers=UA, timeout=15)
        if r.status_code != 200:
            break
        page_rows = parse_page(r.text)
        if not page_rows:
            break
        stop_count = 0
        for row in page_rows:
            k = row["번호"]
            if k in seen:
                stop_count += 1
                continue
            seen[k] = row
        # 같은 번호가 다수 반복되면 더 진행해도 의미 없음
        if stop_count >= 5:
            break
        time.sleep(delay)
    return seen

def main():
    data = crawl(max_pages=50)
    out = sorted(data.values(), key=lambda x: x["번호"])
    with open("../file/service_file/garam_bsb_url.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["번호","제목","URL"])
        w.writeheader()
        w.writerows(out)
    # 콘솔 미리보기
    for r in out[:10]:
        print(r)

if __name__ == "__main__":
    main()
