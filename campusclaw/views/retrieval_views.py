"""Authenticated retrieval and indexing endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from campusclaw import cache, materials, request_context as rc, retrieval, retrieval_db
from campusclaw.chunking import StrategyError, validate_strategy
from campusclaw.errors import ApiError, MESSAGES
from campusclaw.retrieval_config import RetrievalConfig
from campusclaw.views.material_views import parse_material_id

bp = Blueprint("retrieval_api", __name__)


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_QUERY", "需要 JSON 对象")
    return body


def _question(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= 500):
        raise ApiError(400, "INVALID_QUERY", "问题长度须为 1～500 字")
    return value.strip()


def _run_search(question: str, mode: str, limit: int, class_id: int):
    """检索入口：先查缓存，未命中再回源，命中率写进面板。

    缓存键带班级与版本号，跨班不会串；材料写入与索引换代会让版本号 +1，
    该班的旧条目随即作废（TTL 只兜底多进程场景）。
    """
    key = cache.make_key(class_id, mode, question, limit)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        hits = retrieval.search(rc.get_conn(), question, mode, class_id, limit,
                                RetrievalConfig.from_env())
    except retrieval.RetrievalUnavailable as exc:
        raise ApiError(503, "RETRIEVAL_UNAVAILABLE", "检索服务暂不可用") from exc
    # 只缓存命中结果：空结果常在材料刚上传、索引还没跑完时出现，
    # 缓存它会让「等一下再问」也一直是空的。
    if hits:
        cache.put(key, hits)
    return hits


def _public_hit(hit: dict) -> dict:
    return {key: value for key, value in hit.items() if not key.startswith("_")}


@bp.post("/api/search")
def search_api():
    user = rc.require_api_auth()
    body = _body()
    query = _question(body, "query")
    mode = body.get("mode", "hybrid")
    limit = body.get("limit", 10)
    if mode not in ("keyword", "vector", "hybrid") or type(limit) is not int or not 1 <= limit <= 20:
        raise ApiError(400, "INVALID_QUERY", "检索模式或条数不合法")
    hits = _run_search(query, mode, limit, int(user["class_id"]))
    return jsonify({"mode": mode, "hits": [_public_hit(hit) for hit in hits],
                    "message": "" if hits else retrieval.NO_RESULTS}), 200


@bp.post("/api/ask")
def ask_api():
    user = rc.require_api_auth()
    body = _body()
    question = _question(body, "question")
    hits = _run_search(question, "hybrid", 4, int(user["class_id"]))
    if not hits:
        return jsonify({"answer": retrieval.NO_RESULTS, "citations": []}), 200
    try:
        answer = retrieval.answer(question, hits, RetrievalConfig.from_env())
    except retrieval.RetrievalUnavailable as exc:
        raise ApiError(503, "RETRIEVAL_UNAVAILABLE", "回答服务暂不可用") from exc
    return jsonify({"answer": answer, "citations": [
        {"number": n, **_public_hit(hits[n - 1])} for n in retrieval.citation_numbers(answer)
    ]}), 200


@bp.get("/api/materials/<material_id>/index-status")
def index_status_api(material_id: str):
    user = rc.require_api_auth()
    material_id_int = parse_material_id(material_id)
    conn = rc.get_conn()
    if materials.get_active_material(conn, material_id_int, int(user["class_id"])) is None:
        raise ApiError(404, "MATERIAL_NOT_FOUND", MESSAGES["MATERIAL_NOT_FOUND"])
    return jsonify({"material_id": material_id_int,
                    **retrieval_db.index_status(conn, material_id_int)}), 200


@bp.post("/api/materials/<material_id>/reindex")
def reindex_api(material_id: str):
    user = rc.require_write()
    material_id_int = parse_material_id(material_id)
    conn = rc.get_conn()
    if materials.get_active_material(conn, material_id_int, int(user["class_id"])) is None:
        raise ApiError(404, "MATERIAL_NOT_FOUND", MESSAGES["MATERIAL_NOT_FOUND"])
    body = _body()
    try:
        strategy = validate_strategy(body)
    except StrategyError as exc:
        raise ApiError(400, "INVALID_STRATEGY", str(exc)) from exc
    job_id = retrieval_db.enqueue(conn, material_id_int, strategy)
    return jsonify({"material_id": material_id_int, "job_id": job_id,
                    "status": "queued"}), 202
