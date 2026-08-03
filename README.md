# menu-scraper

카카오 채널에서 주간 식단표 이미지를 내려받고 OpenAI `gpt-4o-mini`로 구조화된 JSON을 추출합니다.

## Setup

```bash
uv sync
uv run playwright install chromium
```

프로젝트 루트의 `.env`에 API 키를 설정합니다.

```dotenv
OPENAI_API_KEY=your-api-key
```

프로세스의 `OPENAI_API_KEY` 환경변수가 설정되어 있으면 `.env`보다 우선합니다.
API 키는 소스나 Git에 커밋하지 않습니다.
개인용 또는 관리자 키 대신 이 스크립트 전용 OpenAI 프로젝트의 최소 권한 키를 사용하고, 노출된 키는 즉시 폐기·교체합니다.

## Run

```bash
uv run python main.py
```

## Test

```bash
uv run python -m unittest -v
```
