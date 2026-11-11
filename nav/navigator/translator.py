"""UI-string translation engine and durable job runner.

Uses the Index Translate model (or any spec selected as default_translate)
via its canonical Chinese-language prompt template. The model was trained
on this exact phrasing — English prompts ("Translate this to French")
produce noticeably worse output.

temperature=0.0 is non-negotiable: the model card recommends greedy
decoding, and translation quality degrades sharply with sampling.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .ai.registry import client_for, get_registry
from .db import get_sessionmaker
from .models import TranslationJob, UiString, UiStringTranslation

log = logging.getLogger("navigator.translator")

# Bump when the prompt template changes. Not currently used as part of
# the storage key — admin can click "Refresh {language}" to regenerate.
TRANSLATOR_PROMPT_VERSION = "index-v1"

MAX_CONCURRENT = 6
HEARTBEAT_STALE_SECONDS = 90


# ── Language support ─────────────────────────────────────
#
# 22 core + 128 additional = 150 languages per the model card.
# Codes are ISO 639-1 where available, FLORES-200 3-letter codes for
# the rest (mww, hif, ceb, haw, etc.).
#
# Chinese names drive the prompt template:
#   请将以下英语文本翻译为{中文语言名}，直接输出翻译结果，不要进行任何解释。
#
# Codes are the app's canonical identifiers. Dialects that share a
# parent (Egyptian/Moroccan/Levantine Arabic) map to `ar` and are
# distinguishable only via the prompt text if needed later.

CHINESE_NAMES: dict[str, str] = {
    # ── Core 22 (Table 32) ───────────────────────────────
    "en":  "英语",        "zh":  "中文",
    "de":  "德语",        "fr":  "法语",
    "es":  "西班牙语",    "ja":  "日语",
    "ko":  "韩语",        "pt":  "葡萄牙语",
    "ru":  "俄语",        "ar":  "阿拉伯语",
    "it":  "意大利语",    "nl":  "荷兰语",
    "pl":  "波兰语",      "ro":  "罗马尼亚语",
    "sv":  "瑞典语",      "tr":  "土耳其语",
    "hi":  "印地语",      "vi":  "越南语",
    "th":  "泰语",        "id":  "印度尼西亚语",
    "ms":  "马来语",      "fil": "菲律宾语",

    # ── Additional 128 (Table 33) ────────────────────────
    # European
    "uk": "乌克兰语",  "fa": "波斯语",       "cs": "捷克语",
    "el": "希腊语",    "da": "丹麦语",       "hu": "匈牙利语",
    "fi": "芬兰语",    "nb": "挪威语",       "nn": "新挪威语",
    "sk": "斯洛伐克语", "bg": "保加利亚语",  "bs": "波斯尼亚语",
    "ca": "加泰罗尼亚语","sq": "阿尔巴尼亚语","lv": "拉脱维亚语",
    "hr": "克罗地亚语","lt": "立陶宛语",     "sl": "斯洛文尼亚语",
    "et": "爱沙尼亚语","mk": "马其顿语",     "sr": "塞尔维亚语",
    "is": "冰岛语",    "gl": "加利西亚语",   "be": "白俄罗斯语",
    "af": "南非荷兰语","hy": "亚美尼亚语",   "eu": "巴斯克语",
    "la": "拉丁语",    "cy": "威尔士语",     "ga": "爱尔兰语",
    "mt": "马耳他语",  "lb": "卢森堡语",     "fy": "西弗里西语",
    "fo": "法罗语",    "gd": "苏格兰盖尔语", "co": "科西嘉语",
    "oc": "奥克语",    "se": "北萨米语",     "rm": "罗曼什语",
    "gsw": "瑞士德语", "nds": "低地德语",    "ast": "阿斯图里亚语",
    "roh": "罗曼什语", "nrm": "诺曼语",      "hsb": "上索布语",
    "vec": "威尼斯语",
    # South Asian
    "bn": "孟加拉语",  "ur": "乌尔都语",     "mr": "马拉地语",
    "ta": "泰米尔语",  "ne": "尼泊尔语",     "ml": "马拉雅拉姆语",
    "kn": "卡纳达语",  "gu": "古吉拉特语",   "pa": "旁遮普语",
    "si": "僧伽罗语",  "as": "阿萨姆语",     "sd": "信德语",
    "or": "奥里亚语",  "bo": "藏语",         "my": "缅甸语",
    "km": "高棉语",    "lo": "老挝语",       "dv": "迪维希语",
    # Central & West Asian
    "az": "阿塞拜疆语","kk": "哈萨克语",     "ky": "吉尔吉斯语",
    "uz": "乌兹别克语","tk": "土库曼语",     "tg": "塔吉克语",
    "mn": "蒙古语",    "ka": "格鲁吉亚语",   "ps": "普什图语",
    "ku": "库尔德语",  "ug": "维吾尔语",     "tt": "鞑靼语",
    "ba": "巴什基尔语","cv": "楚瓦什语",     "os": "奥塞梯语",
    "sah": "雅库特语",
    # African
    "am": "阿姆哈拉语","ti": "提格里尼亚语", "so": "索马里语",
    "sw": "斯瓦希里语","ha": "豪萨语",       "yo": "约鲁巴语",
    "ig": "伊博语",    "zu": "祖鲁语",       "xh": "科萨语",
    "st": "塞索托语",  "sn": "绍纳语",       "rw": "卢旺达语",
    "rn": "基隆迪语",  "ny": "齐切瓦语",     "mg": "马达加斯加语",
    "om": "奥罗莫语",  "mg": "马达加斯加语",
    # East & Southeast Asian
    "yue": "粤语",     "ceb": "宿务语",      "jv": "爪哇语",
    "su": "巽他语",    "hil": "希利盖农语",  "mww": "白苗语",
    "hif": "斐济印地语",
    # Pacific & other
    "mi": "毛利语",    "sm": "萨摩亚语",     "haw": "夏威夷语",
    "kl": "格陵兰语",  "to": "汤加语",       "fj": "斐济语",
    "ht": "海地克里奥尔语", "pap": "帕皮阿门托语",
    "eo": "世界语",    "yi": "意第绪语",     "he": "希伯来语",
}

# Locales that get promoted UI buttons. English is the source — it never
# appears here as a target.
PROMOTED_LOCALES: tuple[str, ...] = ("fr", "es", "zh", "pa")


def _signature() -> str:
    spec = get_registry().default_translate()
    return f"{spec.module}:{spec.model}|{TRANSLATOR_PROMPT_VERSION}"


def _build_prompt(text: str, locale: str) -> str:
    """The canonical Chinese template. Do not translate to English —
    the model was trained on this exact phrasing.

    If a locale has no Chinese name registered, we log a warning and
    fall back to a plain English prompt. The output is usually still
    correct, just occasionally less aligned with the model's training
    distribution. Adding a Chinese name is one line in CHINESE_NAMES.
    """
    zh_name = CHINESE_NAMES.get(locale)
    if zh_name is None:
        log.warning("translate.missing_chinese_name locale=%s", locale)
        return (
            f"Translate the following English text to {locale}. "
            f"Output only the translation, no explanation.\n{text}"
        )
    return (
        f"请将以下英语文本翻译为{zh_name}，"
        f"直接输出翻译结果，不要进行任何解释。\n{text}"
    )


async def _llm_translate(text: str, locale: str) -> str:
    spec = get_registry().default_translate()
    client = client_for(spec)
    messages = [{"role": "user", "content": _build_prompt(text, locale)}]
    out = ""
    async for ev in client.stream_chat(spec, messages, temperature=0.0):
        if ev.kind == "delta" and ev.text:
            out += ev.text
        elif ev.kind == "error":
            raise RuntimeError(ev.error or "model error")
        elif ev.kind == "done":
            break
    cleaned = out.strip().strip('"').strip("'").strip()
    if not cleaned:
        raise RuntimeError("model returned empty translation")
    return cleaned


# ── Job lifecycle (unchanged from the durable design) ────

async def claim_job(db: AsyncSession, job_id: uuid.UUID) -> bool:
    stmt = (
        update(TranslationJob)
        .where(
            TranslationJob.id == job_id,
            or_(
                TranslationJob.status.in_(["pending", "failed"]),
                and_(
                    TranslationJob.status == "running",
                    TranslationJob.heartbeat_at
                    < func.now() - text(f"interval '{HEARTBEAT_STALE_SECONDS} seconds'"),
                ),
            ),
        )
        .values(
            status="running",
            started_at=func.coalesce(TranslationJob.started_at, func.now()),
            heartbeat_at=func.now(),
            cancel_requested=False,
        )
        .returning(TranslationJob.id)
    )
    return (await db.execute(stmt)).scalar() is not None


async def _collect_work(
    db: AsyncSession, locale: str | None,
) -> list[tuple[str, str, str]]:
    targets = [locale] if locale else list(CHINESE_NAMES.keys())
    keys = (
        await db.execute(select(UiString.key, UiString.english))
    ).all()
    existing: set[tuple[str, str]] = set(
        (await db.execute(
            select(UiStringTranslation.key, UiStringTranslation.locale)
        )).all()
    )
    work: list[tuple[str, str, str]] = []
    for k in keys:
        for loc in targets:
            if loc == "en":
                continue
            if (k.key, loc) not in existing:
                work.append((k.key, loc, k.english))
    return work


async def run_translation_job(job_id: uuid.UUID) -> None:
    # ── Phase 1: claim and collect work (one short-lived session) ──
    async with get_sessionmaker()() as db:
        if not await claim_job(db, job_id):
            return
        await db.commit()

        job = await db.get(TranslationJob, job_id)
        assert job is not None
        work = await _collect_work(db, job.locale)
        job.total = len(work)
        await db.commit()

    if not work:
        async with get_sessionmaker()() as db:
            await _complete(db, job_id, "done")
        return

    # ── Phase 2: translate (per-worker sessions, no sharing) ──
    #
    # AsyncSession is not concurrency-safe. Each worker must use its
    # own session. The shared `cancelled` Event lets workers short-
    # circuit after one of them observes cancel_requested=true; we
    # deliberately do NOT share sessions to avoid IllegalStateChangeError
    # (session's connection is provisioned lazily, and concurrent
    # provisioning corrupts the session's state machine).
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    signature = _signature()
    cancelled = asyncio.Event()

    async def do_one(item: tuple[str, str, str]) -> None:
        if cancelled.is_set():
            return
        key, loc, english = item
        async with semaphore:
            if cancelled.is_set():
                return

            try:
                translated = await _llm_translate(english, loc)
            except Exception as e:
                log.warning(
                    "translate.failed key=%s locale=%s err=%s",
                    key, loc, e,
                )
                async with get_sessionmaker()() as db:
                    await _bump(db, job_id, failed=1, error=str(e))
                return

            async with get_sessionmaker()() as db:
                await _upsert(db, key, loc, translated, signature)
                was_cancelled = await _bump(db, job_id, done=1)

            if was_cancelled:
                cancelled.set()

    await asyncio.gather(*(do_one(w) for w in work))

    # ── Phase 3: final status (fresh session) ──
    async with get_sessionmaker()() as db:
        if cancelled.is_set() or await _is_cancelled(db, job_id):
            await _complete(db, job_id, "cancelled")
            return
        j = await db.get(TranslationJob, job_id)
        if j and j.failed:
            await _complete(db, job_id, "failed")
        else:
            await _complete(db, job_id, "done")


async def _upsert(
    db: AsyncSession, key: str, locale: str,
    translated: str, signature: str,
) -> None:
    stmt = pg_insert(UiStringTranslation).values(
        key=key, locale=locale, translated=translated,
        translator_signature=signature,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key", "locale"],
        set_={
            "translated": translated,
            "translator_signature": signature,
            "translated_at": func.now(),
        },
    )
    await db.execute(stmt)
    await db.commit()


async def _bump(
    db: AsyncSession, job_id: uuid.UUID,
    done: int = 0, failed: int = 0, error: str | None = None,
) -> bool:
    """Increment counters and return the current cancel_requested flag.

    Returning the flag from the same UPDATE saves a round-trip: each
    worker already commits after every item, so folding the check into
    that commit is free.
    """
    values: dict = {"heartbeat_at": func.now()}
    if done:
        values["done"] = TranslationJob.done + done
    if failed:
        values["failed"] = TranslationJob.failed + failed
    if error:
        values["error_summary"] = error[:2000]
    row = (await db.execute(
        update(TranslationJob)
        .where(TranslationJob.id == job_id)
        .values(**values)
        .returning(TranslationJob.cancel_requested)
    )).scalar()
    await db.commit()
    return bool(row)


async def _is_cancelled(db: AsyncSession, job_id: uuid.UUID) -> bool:
    row = (await db.execute(
        select(TranslationJob.cancel_requested).where(TranslationJob.id == job_id)
    )).scalar()
    return bool(row)


async def _complete(db: AsyncSession, job_id: uuid.UUID, status: str) -> None:
    await db.execute(
        update(TranslationJob)
        .where(TranslationJob.id == job_id)
        .values(status=status, completed_at=func.now(), heartbeat_at=func.now())
    )
    await db.commit()