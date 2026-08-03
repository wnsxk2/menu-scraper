# OpenAI OCR Migration Design

## Goal

Replace the local Ollama OCR request with one OpenAI Responses API request while preserving the scraper, image download, printed JSON structure, and current failure boundary.

## Scope

- Replace the Ollama endpoint, model, request, response parsing, and user-facing labels in `main.py`.
- Use the existing `requests` dependency instead of adding the OpenAI SDK or another HTTP client.
- Use `gpt-4o-mini` as the fixed model.
- Read the API key only from `OPENAI_API_KEY`.
- Preserve the top-level `title` and `weekly_menu` fields. Each menu entry keeps `day_of_week`, `date`, `main_menus`, `side_menus`, and integer `calories`.
- Document configuration and execution in `README.md`.
- Add one small standard-library test module covering the request contract and failure boundary.

## Non-goals

- Retaining Ollama as a fallback.
- Selecting providers or models through configuration.
- Adding the OpenAI SDK, dotenv, a retry library, or new application layers.
- Refactoring the Kakao crawling, image download, console output, or process exit behavior.

## Architecture and Data Flow

`main()` continues to crawl the Kakao channel and save the selected image before calling the renamed OpenAI OCR function. The OCR function owns the complete provider boundary:

1. Read and validate `OPENAI_API_KEY`.
2. Read the downloaded image and detect PNG or JPEG from its bytes rather than its filename.
3. Encode the image as a Base64 data URL using the detected MIME type.
4. Send one non-streaming request to `POST /v1/responses` with `gpt-4o-mini`, `detail: high`, and `store: false`.
5. Require a strict JSON Schema matching the existing menu contract.
6. Find the response message content, reject refusals or incomplete responses, parse the structured JSON, and return the resulting dictionary.

The tracked `weekly_menu.jpg` is PNG data despite its extension, so byte-based MIME detection is part of the provider boundary rather than optional hardening.

## Extraction Rules

- Read weekday and month/day from each table header.
- Produce `date` as `YYYY-MM-DD`, using the execution year because the source image omits the year.
- Put rice, soup, and visually emphasized entree items in `main_menus`.
- Put the remaining dishes in `side_menus` in source order.
- Read `calories` from the calorie row as an integer.
- Do not add keys outside the approved schema.

## Error Handling and Security

The OCR function returns `None` after a concise Korean error for a missing API key, unreadable or unsupported image, timeout, transport failure, non-success HTTP response, malformed API JSON, incomplete response, refusal, missing output text, or invalid structured JSON. The existing caller then prints its current terminal failure message.

Logs must never include the API key, authorization header, Base64 image, or full request body. No Ollama fallback or application-level retry is attempted. A bounded retry can be added later only if production evidence shows recurring transient failures.

## Verification

An offline `unittest` check will mock the OpenAI HTTP request and verify:

- A PNG fixture with a `.jpg` filename is sent as `data:image/png;base64,...`.
- The request uses `gpt-4o-mini`, `detail: high`, `store: false`, bearer authentication, and the strict menu schema.
- A completed structured response returns the unchanged keys and value types.
- Missing credentials, HTTP failure, timeout, refusal, incomplete output, or malformed content returns `None` without leaking secrets.

Final acceptance requires one live run with a valid `OPENAI_API_KEY` against the representative Korean menu image. The result must reproduce all weekday headers, dates, menu grouping, and calorie values. Offline mocks alone do not establish OCR accuracy.

## Sources

- [GPT-4o mini model capabilities](https://developers.openai.com/api/docs/models/gpt-4o-mini)
- [OpenAI image input and detail guidance](https://developers.openai.com/api/docs/guides/images-vision)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
