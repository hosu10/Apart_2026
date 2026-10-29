"""단지명 정규화 및 퍼지 매칭 (Entity Resolution)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from thefuzz import fuzz, process


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip()
    s = re.sub(r"\(.*?\)", "", s)  # 괄호 내용 제거
    s = s.replace("아파트", "").replace("APT", "").replace("Apt", "")
    s = re.sub(r"[^0-9A-Za-z가-힣]", "", s)
    return s.lower()


def normalize_dong(dong: str) -> str:
    if not isinstance(dong, str):
        return ""
    s = dong.strip().replace(" ", "")
    # '서울특별시 마포구 공덕동' → 공덕동
    if "동" in s:
        m = re.search(r"([가-힣0-9]+동)\d*$", s)
        if m:
            return m.group(1)
    return s


@dataclass
class MatchResult:
    source_key: str
    score: int
    method: str


def best_match(
    query_name: str,
    candidates: dict[str, str],
    *,
    min_score: int = 85,
) -> Optional[tuple[str, MatchResult]]:
    """
    candidates: {candidate_id: display_name}
    returns (candidate_id, MatchResult) or None
    """
    if not candidates:
        return None
    q = normalize_name(query_name)
    if not q:
        return None

    # 1) exact normalized
    for cid, name in candidates.items():
        if normalize_name(name) == q:
            return cid, MatchResult(cid, 100, "exact")

    # 2) contains / contained
    for cid, name in candidates.items():
        n = normalize_name(name)
        if not n:
            continue
        if q in n or n in q:
            score = 95 if min(len(q), len(n)) >= 4 else 88
            if score >= min_score:
                return cid, MatchResult(cid, score, "contains")

    # 3) fuzzy — choices dict 시 (value, score, key) 반환
    choices = {cid: normalize_name(name) for cid, name in candidates.items() if normalize_name(name)}
    if not choices:
        return None
    hit = process.extractOne(q, choices, scorer=fuzz.token_sort_ratio)
    if not hit:
        return None
    if len(hit) >= 3:
        _val, score, cid = hit[0], hit[1], hit[2]
    else:
        _val, score = hit[0], hit[1]
        cid = next((k for k, v in choices.items() if v == _val), None)
        if cid is None:
            return None
    if score < min_score:
        return None
    return str(cid), MatchResult(str(cid), int(score), "fuzzy")


def match_within_dong(
    query_name: str,
    dong: str,
    rows: Iterable[dict],
    *,
    name_key: str = "complex_name",
    dong_key: str = "dong",
    id_key: str = "id",
    min_score: int = 85,
) -> Optional[tuple[str, MatchResult]]:
    nd = normalize_dong(dong)
    cands = {
        str(r[id_key]): str(r[name_key])
        for r in rows
        if normalize_dong(str(r.get(dong_key, ""))) == nd or nd in normalize_dong(str(r.get("address", "")))
    }
    # dong 필터가 비면 전체에서 시도하지 않음(오매칭 방지) — 주소에 동이 포함된 경우만
    if not cands:
        cands = {
            str(r[id_key]): str(r[name_key])
            for r in rows
            if nd and nd in normalize_dong(str(r.get("address", r.get(dong_key, ""))))
        }
    return best_match(query_name, cands, min_score=min_score)
