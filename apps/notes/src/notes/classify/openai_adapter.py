"""OpenAI Classifier: structured-output Filing and Russian Gist (notes ticket 05, ADR-015)."""

from __future__ import annotations

import base64
import json
from typing import Any

import openai
from openai.types.chat import ChatCompletionContentPartParam
from pydantic import BaseModel

from notes.classify.port import (
    ClassifierRefused,
    ClassifierRejected,
    ClassifierUnavailable,
    Filing,
    FilingRequest,
)
from shared.obs import get_logger
from shared.pricing import translate_prices

log = get_logger(__name__)

TIMEOUT_S = 60
MAX_COMPLETION_TOKENS = 4000
MAX_SECTIONS = 3

SYSTEM_PROMPT = """\
Ты раскладываешь то, что владелец сохранил «на потом» (ссылки, заметки, файлы, голосовые), \
по его секциям и пишешь суть по-русски.

Тебе дают сохранённое (тип, ссылка, площадка, заголовок, автор, описание, слова владельца, \
имя файла, речь из видео или голосового, от кого переслано) и список секций со slug, \
названием и подсказкой. Иногда приложена картинка: обложка ролика или поста, либо сама сохранённая картинка.

Правила:
- sections: от 1 до 3 slug строго из списка, самые подходящие первыми. Слова владельца \
важнее описания. "other" — только если не подходит ничего.
- gist: одно-два предложения по-русски, без эмодзи и хэштегов: что это и чем может \
пригодиться. Не начинай с «Это» и не пересказывай заголовок дословно.
- title: чистый заголовок без названия сайта, хэштегов и эмодзи, на языке оригинала; \
если заголовка нет — короткий (до 8 слов) по содержанию. Для заметки — короткий \
заголовок по-русски до 8 слов. Для голосового (kind "voice") — так же, как для заметки: \
короткий заголовок по-русски по тому, что сказано; transcript — главный источник.
- author: человек или канал, если это ясно; иначе null. Не выдумывай. sender — тот, кто \
переслал; не копируй его в author.
- Сначала опирайся на слова владельца и описание. Картинку используй, когда описание пусто \
или неясно; для профиля или файла без описания она может быть единственным источником.
- confident: false, если по всему имеющемуся нельзя уверенно понять, о чём это, и начало речи \
из видео помогло бы.
"""


class _Answer(BaseModel):
    sections: list[str]
    gist: str
    title: str | None
    author: str | None
    confident: bool


def render_request(request: FilingRequest) -> str:
    """The user turn: the Item and the current Sections, as JSON the model reads."""
    item = {
        "kind": request.kind,
        "url": request.url,
        "file_name": request.file_name,
        "source": request.source,
        "title": request.title,
        "author": request.author,
        "caption": request.clipped_caption(),
        "transcript": request.clipped_transcript(),
        "owner_words": request.annotation or None,
        "sender": request.sender,
    }
    sections = [{"slug": s.slug, "name": s.name, "hint": s.hint} for s in request.sections]
    return json.dumps({"item": item, "sections": sections}, ensure_ascii=False, indent=1)


class OpenAIClassifier:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self.client = openai.AsyncOpenAI(api_key=api_key, timeout=TIMEOUT_S, max_retries=1)

    async def file(self, request: FilingRequest) -> Filing:
        try:
            response = await self._parse(request)
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            raise ClassifierRefused(exc.__class__.__name__) from exc
        except (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.InternalServerError,
        ) as exc:
            raise ClassifierUnavailable(str(exc)) from exc
        except openai.APIStatusError as exc:
            raise ClassifierRejected(f"HTTP {exc.status_code}: {exc.message}") from exc

        self._log_cost(response)
        message = response.choices[0].message
        if message.refusal:
            raise ClassifierRefused(message.refusal)
        answer = message.parsed
        if answer is None:
            raise ClassifierUnavailable("empty structured answer")
        known = {s.slug for s in request.sections}
        slugs = [slug for slug in dict.fromkeys(answer.sections) if slug in known]
        return Filing(
            sections=slugs[:MAX_SECTIONS],
            gist=answer.gist.strip(),
            title=(answer.title or "").strip() or None,
            author=(answer.author or "").strip() or None,
            confident=answer.confident,
        )

    async def _parse(self, request: FilingRequest) -> Any:
        try:
            return await self._ask(request, with_image=request.image is not None)
        except openai.BadRequestError as exc:
            if request.image is None:
                raise
            log.warning("classifier rejected the image (%s), retrying without it", exc.message)
            return await self._ask(request, with_image=False)

    async def _ask(self, request: FilingRequest, *, with_image: bool) -> Any:
        content: list[ChatCompletionContentPartParam] = [
            {"type": "text", "text": render_request(request)}
        ]
        if with_image and request.image is not None:
            encoded = base64.b64encode(request.image).decode()
            url = f"data:{request.image_mime or 'image/jpeg'};base64,{encoded}"
            content.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
        return await self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format=_Answer,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )

    def _log_cost(self, response: object) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        price_in, price_out = translate_prices(self.model)
        cost = (usage.prompt_tokens * price_in + usage.completion_tokens * price_out) / 1_000_000
        log.info(
            "classified with %s: %d in / %d out tokens, $%.5f",
            self.model,
            usage.prompt_tokens,
            usage.completion_tokens,
            cost,
        )
