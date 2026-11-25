# -*- coding: utf-8 -*-
from difflib import SequenceMatcher

import pandas as pd


def _name_score(a, b):
    a, b = str(a).strip().lower(), str(b).strip().lower()
    if a == b:
        return 0.6, "列名完全一致"
    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.82:
        return 0.35 * ratio, f"列名相近({a}≈{b})"
    return 0.0, None


def _overlap_score(left: pd.Series, right: pd.Series):
    l = set(left.dropna().astype(str).head(8000).unique())
    r = set(right.dropna().astype(str).head(8000).unique())
    if not l or not r:
        return 0.0, None
    inter = len(l & r)
    jaccard = inter / max(len(l | r), 1)
    coverage = inter / max(len(l), 1)
    score = 0.35 * jaccard + 0.2 * min(coverage, 1)
    if score <= 0.02:
        return 0.0, None
    return score, f"取值重合{inter}个(覆盖{coverage:.0%})"


def suggest_joins(datasets):
    """datasets: [{id, name, columns: profile columns, frame?}]"""
    suggestions = []
    for i, left in enumerate(datasets):
        for right in datasets[i + 1:]:
            for lc in left.get("columns") or []:
                for rc in right.get("columns") or []:
                    score = 0.0
                    reasons = []
                    ns, nr = _name_score(lc.get("name"), rc.get("name"))
                    score += ns
                    if nr:
                        reasons.append(nr)
                    if lc.get("inferred") == rc.get("inferred"):
                        score += 0.08
                    if lc.get("role") == "key" and rc.get("role") == "key":
                        score += 0.12
                        reasons.append("两侧都像关联键")
                    elif "key" in (lc.get("role"), rc.get("role")):
                        score += 0.05
                    lf = left.get("frame")
                    rf = right.get("frame")
                    if lf is not None and rf is not None:
                        try:
                            ov, msg = _overlap_score(lf[lc["name"]], rf[rc["name"]])
                            score += ov
                            if msg:
                                reasons.append(msg)
                        except Exception:
                            pass
                    if score >= 0.42:
                        suggestions.append({
                            "left_dataset_id": left["id"],
                            "right_dataset_id": right["id"],
                            "left_dataset": left.get("name"),
                            "right_dataset": right.get("name"),
                            "left_key": lc["name"],
                            "right_key": rc["name"],
                            "how": "left",
                            "score": round(float(score), 4),
                            "confidence": "high" if score >= 0.75 else "medium" if score >= 0.55 else "low",
                            "reasons": reasons,
                        })
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    kept = []
    seen = {}
    for item in suggestions:
        pair = tuple(sorted([item["left_dataset_id"], item["right_dataset_id"]]))
        seen.setdefault(pair, 0)
        if seen[pair] >= 3:
            continue
        seen[pair] += 1
        kept.append(item)
    return kept


def join_key_pairs(join):
    """一条表间关联上的键对。多对键是 AND：必须同时相等才匹配。"""
    keys = join.get("keys")
    pairs = []
    if isinstance(keys, list):
        for item in keys:
            if isinstance(item, dict):
                left = item.get("left_key") or item.get("left")
                right = item.get("right_key") or item.get("right")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                left, right = item[0], item[1]
            else:
                left = right = None
            if left and right:
                pair = (str(left), str(right))
                if pair not in pairs:
                    pairs.append(pair)
    if not pairs:
        left, right = join.get("left_key"), join.get("right_key")
        if left and right:
            pairs.append((str(left), str(right)))
    if not pairs:
        raise ValueError("关联键不能为空")
    return pairs


def _group_joins(joins):
    """同一对表、同一 how 的多条规则合并成一组 AND 键。"""
    grouped = []
    index = {}
    for raw in joins or []:
        join = dict(raw)
        left_id = int(join["left_dataset_id"])
        right_id = int(join["right_dataset_id"])
        how = join.get("how") or "left"
        key = (left_id, right_id, how)
        pairs = join_key_pairs(join)
        if key in index:
            bucket = grouped[index[key]]["pairs"]
            for pair in pairs:
                if pair not in bucket:
                    bucket.append(pair)
        else:
            index[key] = len(grouped)
            grouped.append({
                "left_dataset_id": left_id,
                "right_dataset_id": right_id,
                "how": how,
                "pairs": list(pairs),
            })
    return grouped


def _merge_on(result, other, result_keys, other_keys, how, other_id):
    missing_l = [c for c in result_keys if c not in result.columns]
    if missing_l:
        raise ValueError(f"左表字段 {', '.join(missing_l)} 不在当前结果中，请检查关联顺序")
    missing_r = [c for c in other_keys if c not in other.columns]
    if missing_r:
        raise ValueError(f"右表字段 {', '.join(missing_r)} 不存在")
    overlap = [c for c in other.columns if c in result.columns and c not in other_keys]
    if overlap:
        other = other.rename(columns={c: f"{c}__d{other_id}" for c in overlap})
        other_keys = [c if c not in overlap else f"{c}__d{other_id}" for c in other_keys]
    for col in result_keys:
        result[col] = result[col].astype(str)
    for col in other_keys:
        other[col] = other[col].astype(str)
    merged = result.merge(
        other, left_on=result_keys, right_on=other_keys, how=how, suffixes=("", f"__d{other_id}")
    )
    drop = [rk for lk, rk in zip(result_keys, other_keys) if rk != lk and rk in merged.columns]
    if drop:
        merged = merged.drop(columns=drop)
    return merged


def apply_joins(frames_by_id, fact_id, joins, required_ids=None):
    """
    从事实表出发，按关联规则链式合并多张表。
    同一对表上的多个键是 AND（row_key、ts、site 同时相等才匹配）。
    """
    fact_id = int(fact_id)
    if fact_id not in frames_by_id:
        raise ValueError("事实表不存在")
    if not joins:
        raise ValueError("请至少配置一条关联字段")

    result = frames_by_id[fact_id].copy()
    used = {fact_id}
    remaining = _group_joins(joins)
    guard = 0
    max_steps = max(len(remaining) * 3, 20)

    while remaining and guard < max_steps:
        guard += 1
        progressed = False
        nxt = []
        for join in remaining:
            left_id = int(join["left_dataset_id"])
            right_id = int(join["right_dataset_id"])
            how = join.get("how") or "left"
            pairs = join["pairs"]
            lkeys = [a for a, _ in pairs]
            rkeys = [b for _, b in pairs]

            if left_id in used and right_id in frames_by_id and right_id not in used:
                right = frames_by_id[right_id].copy()
                result = _merge_on(result, right, lkeys, rkeys, how, right_id)
                used.add(right_id)
                progressed = True
            elif right_id in used and left_id in frames_by_id and left_id not in used:
                left = frames_by_id[left_id].copy()
                result = _merge_on(result, left, rkeys, lkeys, how, left_id)
                used.add(left_id)
                progressed = True
            else:
                nxt.append(join)
        remaining = nxt
        if not progressed:
            break

    if remaining:
        bad = []
        for j in remaining:
            keys = " AND ".join(f"{a}={b}" for a, b in j.get("pairs") or [])
            bad.append(
                f"{j.get('left_dataset_id')} {j.get('how') or 'left'} {j.get('right_dataset_id')} ({keys})"
            )
        raise ValueError(
            "有关联规则无法接入当前结果（两端都未与事实表连通）。"
            "多表关联需从事实表逐步连上每一张表。未应用规则：" + "；".join(bad)
        )

    required = {int(i) for i in (required_ids if required_ids is not None else frames_by_id.keys())}
    missing = sorted(required - used)
    if missing:
        raise ValueError(
            f"以下表未能关联进结果（请补上从事实表可达的关联规则）：{missing}"
        )
    return result


def resolve_selected_columns(merged_columns, selected_fields):
    """
    selected_fields: [{dataset_id, name}]
    将源表字段映射到合并后的列名（同名冲突列为 name__d{id}）。
    """
    if not selected_fields:
        return list(merged_columns)
    cols = []
    available = set(merged_columns)
    for item in selected_fields:
        name = (item or {}).get("name")
        if not name:
            continue
        ds_id = (item or {}).get("dataset_id")
        candidates = [name]
        if ds_id is not None:
            candidates.append(f"{name}__d{int(ds_id)}")
            candidates.append(f"{name}_d{int(ds_id)}")
        for c in candidates:
            if c in available and c not in cols:
                cols.append(c)
                break
    return cols or list(merged_columns)
