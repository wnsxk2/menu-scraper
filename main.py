import os
import re
import time
import base64
import json
from pathlib import Path

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ----------------------------------------------------
# 설정 (OpenAI API 및 카카오 채널 URL)
# ----------------------------------------------------
TARGET_URL = "https://pf.kakao.com/_exdxors/posts"
OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-4o"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ENV_FILE = Path(__file__).with_name(".env")

MENU_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "weekly_menu": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day_of_week": {
                        "type": "string",
                        "enum": ["월", "화", "수", "목", "금", "토", "일"],
                    },
                    "date": {"type": "string"},
                    "main_menus": {"type": "array", "items": {"type": "string"}},
                    "side_menus": {"type": "array", "items": {"type": "string"}},
                    "calories": {"type": "integer"},
                },
                "required": [
                    "day_of_week",
                    "date",
                    "main_menus",
                    "side_menus",
                    "calories",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "weekly_menu"],
    "additionalProperties": False,
}

# ----------------------------------------------------
# 1. Playwright 크롤링
# ----------------------------------------------------
def fetch_menu_image_url():
    """요청해주신 CSS 셀렉터 구조를 활용하여 식단표 이미지를 크롤링합니다."""
    print("1. Playwright 크롤링 시작...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TARGET_URL)
        
        try:
            page.wait_for_selector(".tit_card", timeout=10000)
        except Exception as e:
            print(f"❌ 페이지 로딩 실패: {e}")
            browser.close()
            return None

        page.evaluate("window.scrollBy(0, 500)")
        page.wait_for_timeout(1000)

        # 요청해주신 특정 계층 셀렉터 반영
        cards = page.query_selector_all(
            "div#root > div#kakaoWrap > div#kakaoContent > div#mArticle > div.wrap_webview"
        )
        date_pattern = re.compile(r'\d+\s*월\s*\d+\s*일\s*~\s*\d+\s*월\s*\d+\s*일')
        
        target_img_url = None
        for card in cards:
            title_element = card.query_selector(".tit_card")
            if title_element:
                title_text = title_element.inner_text().strip()
                if "식단표" in title_text and date_pattern.search(title_text):
                    print(f"✅ 대상 게시글 포착: {title_text}")
                    img_element = card.query_selector("img")
                    if img_element:
                        src = img_element.get_attribute("src")
                        if src and "kakaocdn.net" in src:
                            target_img_url = src
                            break
        browser.close()
        return target_img_url

# ----------------------------------------------------
# 2. OpenAI Responses API 기반 VLM OCR 추론
# ----------------------------------------------------
def detect_image_mime(image_data: bytes) -> str:
    if image_data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError("지원하지 않는 이미지 형식입니다. PNG 또는 JPEG가 필요합니다.")


def load_openai_api_key() -> str:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    return os.environ.get("OPENAI_API_KEY", "").strip()


def run_openai_ocr(image_path: str) -> dict | None:
    """주간 식단표 이미지를 OpenAI Responses API로 구조화합니다."""
    print(f"2. OpenAI 모델({OPENAI_MODEL})로 OCR 요청 중...")

    try:
        api_key = load_openai_api_key()
        if not api_key:
            raise ValueError("OPENAI_API_KEY 환경변수 또는 .env 설정이 필요합니다.")

        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
        if not image_data:
            raise ValueError("이미지 파일이 비어 있습니다.")
        if len(image_data) > MAX_IMAGE_BYTES:
            raise ValueError("이미지는 10 MiB 이하여야 합니다.")
        mime_type = detect_image_mime(image_data)
        encoded_image = base64.b64encode(image_data).decode("utf-8")
        current_year = time.localtime().tm_year

        prompt = f"""이미지 속 주간 식단표를 정확히 추출해라.
날짜는 이미지의 월/일과 실행 연도 {current_year}를 조합해 YYYY-MM-DD로 작성한다.
강조된 주메뉴는 main_menus에, 나머지는 side_menus에 원문 순서대로 넣는다.
원산지 표시는 제외하고 메뉴명만 추출한다.
칼로리는 표 하단 값을 정수로 읽고, 이미지에 없는 값은 추측하지 않는다.
필수 값 하나라도 없거나 명확히 읽을 수 없으면 값을 만들지 말고 요청을 거부한다.
"""
        payload = {
            "model": OPENAI_MODEL,
            "store": False,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{encoded_image}",
                            "detail": "high",
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "weekly_menu",
                    "strict": True,
                    "schema": MENU_SCHEMA,
                }
            },
        }
        response = requests.post(
            OPENAI_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("status") != "completed":
            reason = result.get("incomplete_details", {}).get("reason", "unknown")
            raise ValueError(f"OpenAI 응답이 완료되지 않았습니다: {reason}")

        text_parts = []
        for output in result.get("output", []):
            if output.get("type") != "message":
                continue
            for content in output.get("content", []):
                if content.get("type") == "refusal":
                    raise ValueError("OpenAI가 OCR 요청을 거부했습니다.")
                if content.get("type") == "output_text" and content.get("text"):
                    text_parts.append(content["text"])

        if text_parts:
            return json.loads("".join(text_parts))

        raise ValueError("OpenAI 응답에 구조화된 JSON 콘텐츠가 없습니다.")
    except Exception as error:
        print(f"❌ OpenAI API 호출 또는 JSON 처리 에러: {error}")
        return None

# ----------------------------------------------------
# 3. 메인 실행부
# ----------------------------------------------------
def main():
    print("=== [그린블루 백오피스] 주간 식단표 크롤링 & OpenAI OCR 파이프라인 ===")
    
    # Step 1. 식단표 이미지 URL 크롤링
    img_url = fetch_menu_image_url()
    if not img_url:
        print("❌ 식단표 이미지를 수집하지 못했습니다.")
        return

    # Step 2. 이미지 다운로드
    img_data = requests.get(img_url).content
    saved_path = "weekly_menu.jpg"
    with open(saved_path, "wb") as f:
        f.write(img_data)
    print(f"💾 이미지 저장 완료: {saved_path}")

    # Step 3. OpenAI 추론 실행
    start_time = time.time()
    menu_data = run_openai_ocr(saved_path)
    
    print(f"\n⏱️ 소요시간: {time.time() - start_time:.2f}초")
    if menu_data is None:
        print("❌ 주간 식단표 JSON 데이터를 처리하지 못했습니다.")
        return

    print("\n================ [추출된 주간 식단표 (JSON)] ====================")
    print(json.dumps(menu_data, ensure_ascii=False, indent=2))
    print("==================================================================")

if __name__ == "__main__":
    main()
