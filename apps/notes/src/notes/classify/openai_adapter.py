"""OpenAI Classifier: structured-output Filing and Russian Gist (notes ticket 05, ADR-015)."""

from __future__ import annotations

import json

import openai
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
Ты раскладываешь то, что владелец сохранил «на потом» (ссылки и заметки), по его секциям \
и пишешь суть по-русски.

Тебе дают сохранённое (тип, ссылка, площадка, заголовок, автор, описание, слова владельца) \
и список секций со slug, названием и подсказкой.

Правила:
- sections: от 1 до 3 slug строго из списка, самые подходящие первыми. Слова владельца \
важнее описания. "other" — только если не подходит ничего.
- gist: одно-два предложения по-русски, без эмодзи и хэштегов: что это и чем может \
пригодиться. Не начинай с «Это» и не пересказывай заголовок дословно.
- title: чистый заголовок без названия сайта, хэштегов и эмодзи, на языке оригинала; \
если заголовка нет — короткий (до 8 слов) по содержанию. Для заметки — короткий \
заголовок по-русски до 8 слов.
- author: человек или канал, если это ясно; иначе null. Не выдумывай.
"""


class _Answer(BaseModel):
    sections: list[str]
    gist: str
    title: str | None
    author: str | None


def render_request(request: FilingRequest) -> str:
    """The user turn: the Item and the current Sections, as JSON the model reads."""
    item = {
        "kind": request.kind,
        "url": request.url,
        "source": request.source,
        "title": request.title,
        "author": request.author,
        "caption": request.clipped_caption(),
        "owner_words": request.annotation or None,
    }
    sections = [{"slug": s.slug, "name": s.name, "hint": s.hint} for s in request.sections]
    return json.dumps({"item": item, "sections": sections}, ensure_ascii=False, indent=1)


class OpenAIClassifier:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self.client = openai.AsyncOpenAI(api_key=api_key, timeout=TIMEOUT_S, max_retries=1)

    async def file(self, request: FilingRequest) -> Filing:
        try:
            response = await self.client.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": render_request(request)},
                ],
                response_format=_Answer,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
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
