import os
import re
import time
import base64
import json
import requests
from playwright.sync_api import sync_playwright

# ----------------------------------------------------
# 설정 (Ollama 서버 및 카카오 채널 URL)
# ----------------------------------------------------
TARGET_URL = "https://pf.kakao.com/_exdxors/posts"
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3.5:4b"  # 또는 ollama에 구동 중인 비전 모델명 (ex: minicpm-v, llama3.2-vision 등)

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
# 2. Ollama API 기반 VLM OCR 추론
# ----------------------------------------------------
def run_ollama_ocr(image_path: str) -> dict | None:
    """다운로드한 이미지를 base64로 인코딩하여 Ollama API로 전달합니다."""
    print(f"2. Ollama 모델({OLLAMA_MODEL})로 OCR 요청 중...")
    
    # 1. 이미지 파일을 base64 문자열로 변환
    with open(image_path, "rb") as f:
        encoded_image = base64.b64encode(f.read()).decode("utf-8")

    # 2. Ollama API 요청 페이로드 구성
    prompt = """이미지 속 주간 식단표를 분석하여 아래 JSON 포맷으로만 출력해줘. 다른 설명이나 마크다운 텍스트 없이 Pure JSON 데이터만 반환해줘.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "format": "json",
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [encoded_image]
            }
        ],
        "stream": False
    }

    # 3. HTTP POST 요청
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        response.raise_for_status()
        result_json = response.json()
        content = result_json.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Ollama 응답에 JSON 콘텐츠가 없습니다.")
        return json.loads(content)
    except Exception as e:
        print(f"❌ Ollama API 호출 또는 JSON 처리 에러: {e}")
        return None

# ----------------------------------------------------
# 3. 메인 실행부
# ----------------------------------------------------
def main():
    print("=== [그린블루 백오피스] 주간 식단표 크롤링 & Ollama OCR 파이프라인 ===")
    
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

    # Step 3. Ollama 추론 실행
    start_time = time.time()
    menu_data = run_ollama_ocr(saved_path)
    
    print(f"\n⏱️ 소요시간: {time.time() - start_time:.2f}초")
    if menu_data is None:
        print("❌ 주간 식단표 JSON 데이터를 처리하지 못했습니다.")
        return

    print("\n================ [추출된 주간 식단표 (JSON)] ====================")
    print(json.dumps(menu_data, ensure_ascii=False, indent=2))
    print("==================================================================")

if __name__ == "__main__":
    main()
