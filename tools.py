import os
import re
import numpy as np
import pandas as pd

# 집계 행 감지에 사용할 표준 키워드 목록
AGGREGATE_KEYWORDS = [
    "world", "oecd", "euro area", "european union", "high income",
    "low income", "income", "area", "total", "dividend", "small states",
    "middle income", "upper middle income", "lower middle income",
    "ida & ibrd", "sub-saharan", "latin america", "arab world"
]

def sanitize_value(val):
    """NaN, Inf 값을 JSON 직렬화가 가능한 None 또는 유효 숫자로 변환합니다."""
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, (float, np.floating)):
        if np.isnan(val) or np.isinf(val):
            return None
        return round(float(val), 4)
    if isinstance(val, (int, np.integer)):
        return int(val)
    return val

def get_text_label_column(df, label_column=None):
    """레이블 컬럼이 지정되지 않은 경우 첫 번째 텍스트 컬럼을 탐색합니다."""
    if label_column and label_column in df.columns:
        return label_column
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) and not str(c).startswith("Unnamed:"):
            return str(c)
    return str(df.columns[0])

def find_year_columns(df):
    """4자리 연도(1960~2099) 형식의 컬럼 목록을 반환합니다."""
    return [
        str(c) for c in df.columns
        if re.match(r"^(19|20)\d{2}$", str(c).strip())
    ]

def filter_aggregates_df(df, label_column=None):
    """
    집계 행(World, High income 등)을 탐지하여 필터링된 데이터프레임과 제외된 인덱스를 반환합니다.
    """
    col = get_text_label_column(df, label_column)
    if not col:
        return df, []
    
    mask = df[col].astype(str).str.lower().apply(
        lambda v: any(kw in v for kw in AGGREGATE_KEYWORDS)
    )
    excluded_indices = df[mask].index.tolist()
    filtered_df = df[~mask].copy()
    return filtered_df, excluded_indices

def try_merge_metadata(df):
    """
    data 폴더에 Metadata_Country 파일이 존재하는 경우 Region 및 IncomeGroup 컬럼을 자동 병합합니다.
    """
    if "Region" in df.columns or "Country Code" not in df.columns:
        return df
    
    meta_candidates = [
        r"data\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465\Metadata_Country_API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv",
        "data/Metadata_Country.csv"
    ]
    for p in meta_candidates:
        if os.path.exists(p):
            try:
                mdf = pd.read_csv(p, encoding="utf-8-sig")
                cols_to_use = [c for c in ["Country Code", "Region", "IncomeGroup"] if c in mdf.columns]
                if "Country Code" in cols_to_use and len(cols_to_use) > 1:
                    return pd.merge(df, mdf[cols_to_use], on="Country Code", how="left")
            except Exception:
                pass
    return df

# ==============================================================================
# 도구 1: reshape_wide_to_long (연도 열을 행으로 접기)
# ==============================================================================
def reshape_wide_to_long(df, id_vars=None, value_name="Value", var_name="Year", exclude_aggregates=True):
    year_cols = find_year_columns(df)
    if not year_cols:
        raise ValueError("변환할 연도 열을 찾을 수 없습니다.")

    working_df = df.copy()
    rows_excluded = 0
    exclusion_reason_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_reason_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    if id_vars is None:
        id_vars = [str(c) for c in working_df.columns if str(c) not in year_cols and not str(c).startswith("Unnamed:")]

    melted = pd.melt(working_df, id_vars=id_vars, value_vars=year_cols, var_name=var_name, value_name=value_name)
    melted_clean = melted.dropna(subset=[value_name]).copy()

    sample_records = melted_clean.head(20).to_dict(orient="records")
    for r in sample_records:
        for k, v in r.items():
            r[k] = sanitize_value(v)

    ref_period = f"{year_cols[0]} ~ {year_cols[-1]}년"
    exclusion_reason = ", ".join(exclusion_reason_parts) if exclusion_reason_parts else "제외 항목 없음"

    return {
        "tool": "reshape_wide_to_long",
        "result": {
            "total_records": len(melted_clean),
            "id_columns": id_vars,
            "year_range": [year_cols[0], year_cols[-1]],
            "sample": sample_records
        },
        "reference_period": ref_period,
        "rows_used": len(melted_clean),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": id_vars + [var_name, value_name],
        "unit": "행 (Records)",
        "cautions": "가로 형태를 세로 형태로 변환하며 결측치가 존재하는 연도 관측치는 제외되었습니다."
    }

# ==============================================================================
# 도구 2: quality_report (결측·중복·타입·이상한 열 이름)
# ==============================================================================
def quality_report(df, exclude_aggregates=False):
    total_rows = len(df)
    total_cols = len(df.columns)
    unnamed_cols = [str(c) for c in df.columns if str(c).startswith("Unnamed:") or str(c).strip() == ""]
    empty_cols = [str(c) for c in df.columns if df[c].isna().all()]

    col_missing = {}
    for c in df.columns:
        m = int(df[c].isna().sum())
        col_missing[str(c)] = {
            "missing_count": m,
            "missing_ratio": round(m / total_rows, 4) if total_rows > 0 else 0.0,
            "dtype": str(df[c].dtype)
        }

    return {
        "tool": "quality_report",
        "result": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "duplicate_rows": int(df.duplicated().sum()),
            "unnamed_columns": unnamed_cols,
            "all_empty_columns": empty_cols,
            "columns_detail": col_missing
        },
        "reference_period": "전체 데이터 (전수 검사)",
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reason": "품질 진단 목적이므로 전체 원본 데이터를 사용했습니다.",
        "columns_used": [str(c) for c in df.columns],
        "unit": "건 / %",
        "cautions": "품질 보고서는 데이터 정제 필요성을 평가하기 위한 전처리 진단 결과입니다."
    }

# ==============================================================================
# 도구 3: year_coverage (연도별 값 개수와 권장 기준연도)
# ==============================================================================
def year_coverage(df, exclude_aggregates=True):
    year_cols = find_year_columns(df)
    if not year_cols:
        raise ValueError("분석할 연도 열이 존재하지 않습니다.")

    working_df = df.copy()
    rows_excluded = 0
    exclusion_reason = "제외 없음"

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df)
        rows_excluded = len(excluded_idx)
        exclusion_reason = f"대륙/소득 집계 행 {rows_excluded}건 제외"

    total_items = len(working_df)
    coverage_data = {}
    chart_labels = []
    chart_values = []

    for y in year_cols:
        filled = int(working_df[y].notna().sum())
        ratio = round(filled / total_items, 4) if total_items > 0 else 0.0
        coverage_data[str(y)] = {
            "filled_count": filled,
            "total": total_items,
            "ratio": ratio
        }
        chart_labels.append(str(y))
        chart_values.append(filled)

    max_filled = max((v["filled_count"] for v in coverage_data.values()), default=0)
    threshold = max_filled * 0.8
    valid_years = [y for y, v in coverage_data.items() if v["filled_count"] >= threshold]
    recommended_year = valid_years[-1] if valid_years else year_cols[-1]

    return {
        "tool": "year_coverage",
        "result": {
            "coverage_by_year": coverage_data,
            "recommended_year": recommended_year,
            "chart_data": {
                "type": "bar",
                "labels": chart_labels,
                "values": chart_values
            }
        },
        "reference_period": f"{year_cols[0]} ~ {year_cols[-1]}년",
        "rows_used": total_items,
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": year_cols,
        "unit": "개 (유효 관측치 수)",
        "cautions": "가장 최근 연도라도 보고 지연 등으로 결측치가 심할 수 있으므로 권장 기준연도 확인이 필수적입니다."
    }

# ==============================================================================
# 도구 4: detect_aggregates (집계 행 후보 탐지)
# ==============================================================================
def detect_aggregates(df, label_column=None):
    col = get_text_label_column(df, label_column)
    total_rows = len(df)
    candidates = [{"index": int(idx), "name": str(val)} for idx, val in df[col].items() if any(kw in str(val).lower() for kw in AGGREGATE_KEYWORDS)]
    return {
        "tool": "detect_aggregates",
        "result": {
            "target_column": col,
            "total_rows": total_rows,
            "aggregate_count": len(candidates),
            "pure_entities_count": total_rows - len(candidates),
            "sample_aggregates": [c["name"] for c in candidates[:10]],
            "all_aggregates": candidates
        },
        "reference_period": "전체 데이터",
        "rows_used": total_rows,
        "rows_excluded": 0,
        "exclusion_reason": "전체 데이터에서 집계 행을 탐지하기 위해 모든 행을 검사했습니다.",
        "columns_used": [col],
        "unit": "건",
        "cautions": "집계 행을 개별 국가 순위나 평균 계산에 포함하면 대륙 합계와 개별 국가가 중복 집계되는 통계 왜곡이 발생합니다."
    }

# ==============================================================================
# 도구 5: describe_numeric (개수·평균·중앙값·최소·최대·표준편차)
# ==============================================================================
def describe_numeric(df, value_column=None, reference_period=None, exclude_aggregates=True):
    if reference_period and str(reference_period) in df.columns:
        value_column = str(reference_period)
    elif value_column is None:
        year_cols = find_year_columns(df)
        if year_cols:
            value_column = year_cols[-1]
        else:
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            if not num_cols:
                raise ValueError("분석할 수치형 열이 데이터셋에 존재하지 않습니다.")
            value_column = num_cols[0]

    working_df = df.copy()
    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    series = pd.to_numeric(working_df[value_column], errors="coerce").dropna()
    null_count = len(working_df) - len(series)
    if null_count > 0:
        rows_excluded += null_count
        exclusion_parts.append(f"결측치 {null_count}건 제외")

    if len(series) == 0:
        raise ValueError(f"선택한 열 '{value_column}'에 유효한 수치 데이터가 없습니다.")

    stats = {
        "count": int(series.count()),
        "mean": sanitize_value(series.mean()),
        "std": sanitize_value(series.std()),
        "min": sanitize_value(series.min()),
        "q25": sanitize_value(series.quantile(0.25)),
        "median": sanitize_value(series.median()),
        "q75": sanitize_value(series.quantile(0.75)),
        "max": sanitize_value(series.max())
    }

    ref_period = str(reference_period) if reference_period else str(value_column)
    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "describe_numeric",
        "result": {
            "column": value_column,
            "statistics": stats
        },
        "reference_period": ref_period,
        "rows_used": len(series),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [value_column],
        "unit": "수치 (요약 통계)",
        "cautions": "평균은 극단적인 최상위/최하위 값(이상치)의 영향을 크게 받으므로 반드시 중앙값과 함께 비교해야 합니다."
    }

# ==============================================================================
# 도구 6: trend_line (선택 항목들의 연도별 추이 - 선 차트)
# ==============================================================================
def trend_line(df, items=None, label_column=None, start_year=None, end_year=None, exclude_aggregates=False):
    year_cols = find_year_columns(df)
    if not year_cols:
        raise ValueError("시계열 추이를 그릴 연도 열이 존재하지 않습니다.")

    col = get_text_label_column(df, label_column)
    
    if not items:
        default_candidates = ["Korea, Rep.", "United States", "World", "Germany", "Japan"]
        existing = df[col].astype(str).tolist()
        items = [cand for cand in default_candidates if cand in existing]
        if not items:
            items = existing[:3]

    target_years = year_cols
    if start_year and str(start_year) in target_years:
        idx_s = target_years.index(str(start_year))
        target_years = target_years[idx_s:]
    if end_year and str(end_year) in target_years:
        idx_e = target_years.index(str(end_year))
        target_years = target_years[:idx_e + 1]

    datasets = []
    summary_rows = []
    used_count = 0

    for item_name in items:
        row = df[df[col].astype(str) == str(item_name)]
        if not row.empty:
            used_count += 1
            vals = [sanitize_value(pd.to_numeric(row[y].values[0], errors="coerce")) for y in target_years]
            datasets.append({
                "label": str(item_name),
                "data": vals
            })
            summary_rows.append({
                "item": str(item_name),
                "start_val": vals[0],
                "end_val": vals[-1]
            })

    excluded_items = len(items) - used_count
    ref_period = f"{target_years[0]} ~ {target_years[-1]}년"
    exclusion_reason = f"데이터셋에서 찾을 수 없는 항목 {excluded_items}건 제외" if excluded_items > 0 else "제외 항목 없음"

    return {
        "tool": "trend_line",
        "result": {
            "selected_items": items,
            "chart_data": {
                "type": "line",
                "labels": target_years,
                "datasets": datasets
            },
            "summary_table": summary_rows
        },
        "reference_period": ref_period,
        "rows_used": used_count,
        "rows_excluded": excluded_items,
        "exclusion_reason": exclusion_reason,
        "columns_used": [col] + target_years,
        "unit": "% (지표 수치)",
        "cautions": "과거 시점에는 조사가 시행되지 않아 특정 연도에 결측치(선 끊김)가 발생할 수 있습니다."
    }

# ==============================================================================
# 도구 7: top_bottom_n (기준연도 기준 상위·하위 N - 수평 막대)
# ==============================================================================
def top_bottom_n(df, reference_period, value_column=None, label_column=None, n=10, mode="top", exclude_aggregates=True):
    if not reference_period or str(reference_period).strip() == "":
        raise ValueError("top_bottom_n 도구는 기준 시점(reference_period)이 필수입니다.")

    ref_str = str(reference_period).strip()
    target_col = value_column if (value_column and value_column in df.columns) else ref_str
    if target_col not in df.columns:
        raise ValueError(f"지정한 기준 시점 열 '{target_col}'이 데이터셋에 존재하지 않습니다.")

    col = get_text_label_column(df, label_column)
    working_df = df.copy()
    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df, col)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    working_df[target_col] = pd.to_numeric(working_df[target_col], errors="coerce")
    valid_df = working_df.dropna(subset=[target_col]).copy()
    null_count = len(working_df) - len(valid_df)
    if null_count > 0:
        rows_excluded += null_count
        exclusion_parts.append(f"{ref_str}년 결측치 {null_count}건 제외")

    if valid_df.empty:
        raise ValueError(f"기준 시점 '{ref_str}'에 유효한 데이터가 0건입니다.")

    n = max(1, int(n))
    top_df = valid_df.sort_values(by=target_col, ascending=False).head(n)
    bottom_df = valid_df.sort_values(by=target_col, ascending=True).head(n)

    display_df = bottom_df if mode == "bottom" else top_df
    chart_labels = [str(x) for x in display_df[col].tolist()]
    chart_values = [sanitize_value(x) for x in display_df[target_col].tolist()]

    top_records = [{"rank": i+1, "label": str(r[col]), "value": sanitize_value(r[target_col])} for i, (_, r) in enumerate(top_df.iterrows())]
    bottom_records = [{"rank": i+1, "label": str(r[col]), "value": sanitize_value(r[target_col])} for i, (_, r) in enumerate(bottom_df.iterrows())]

    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "top_bottom_n",
        "result": {
            "mode": mode,
            "n": n,
            "top_records": top_records,
            "bottom_records": bottom_records,
            "chart_data": {
                "type": "bar",
                "horizontal": True,
                "labels": chart_labels,
                "values": chart_values
            }
        },
        "reference_period": f"{ref_str}년 단일 시점",
        "rows_used": len(valid_df),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [col, target_col],
        "unit": "% (지표 수치)",
        "cautions": f"시점 불일치 오류를 방지하기 위해 오직 {ref_str}년에 공식 보고된 수치만으로 순위를 매겼습니다."
    }

# ==============================================================================
# 도구 8: group_summary (그룹별 평균·합계·개수 - 막대)
# ==============================================================================
def group_summary(df, reference_period, group_column=None, value_column=None, agg_func="mean", exclude_aggregates=True):
    if not reference_period or str(reference_period).strip() == "":
        raise ValueError("group_summary 도구는 기준 시점(reference_period)이 필수입니다.")

    ref_str = str(reference_period).strip()
    target_col = value_column if (value_column and value_column in df.columns) else ref_str
    if target_col not in df.columns:
        raise ValueError(f"지정한 기준 시점 열 '{target_col}'이 데이터셋에 존재하지 않습니다.")

    working_df = try_merge_metadata(df.copy())

    if not group_column or group_column not in working_df.columns:
        for cand in ["Region", "IncomeGroup", "Indicator Name"]:
            if cand in working_df.columns:
                group_column = cand
                break
        if not group_column or group_column not in working_df.columns:
            raise ValueError("그룹화할 범주형 열(예: Region, IncomeGroup)을 찾을 수 없습니다.")

    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    working_df[target_col] = pd.to_numeric(working_df[target_col], errors="coerce")
    valid_df = working_df.dropna(subset=[target_col, group_column]).copy()
    valid_df = valid_df[valid_df[group_column].astype(str).str.strip() != ""]

    total_excluded = len(df) - len(valid_df)
    if total_excluded > rows_excluded:
        diff = total_excluded - rows_excluded
        exclusion_parts.append(f"그룹 결측치 {diff}건 제외")
        rows_excluded = total_excluded

    if valid_df.empty:
        raise ValueError(f"그룹 집계를 수행할 유효 데이터가 없습니다 ({ref_str}년).")

    grouped = valid_df.groupby(group_column)[target_col].agg(
        mean="mean", sum="sum", count="count", median="median"
    ).reset_index()

    grouped = grouped.sort_values(by=agg_func if agg_func in grouped.columns else "mean", ascending=False)

    chart_labels = [str(x) for x in grouped[group_column].tolist()]
    chart_values = [sanitize_value(x) for x in grouped[agg_func if agg_func in grouped.columns else "mean"].tolist()]

    group_records = []
    for _, r in grouped.iterrows():
        group_records.append({
            "group": str(r[group_column]),
            "mean": sanitize_value(r["mean"]),
            "median": sanitize_value(r["median"]),
            "count": int(r["count"]),
            "sum": sanitize_value(r["sum"])
        })

    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "group_summary",
        "result": {
            "group_column": group_column,
            "agg_func": agg_func,
            "groups": group_records,
            "chart_data": {
                "type": "bar",
                "labels": chart_labels,
                "values": chart_values
            }
        },
        "reference_period": f"{ref_str}년 단일 시점",
        "rows_used": len(valid_df),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [group_column, target_col],
        "unit": f"% (그룹별 {agg_func})",
        "cautions": "그룹별 평균은 각 국가의 인구 규모를 고려하지 않은 단순 산술 평균(국가당 동일 가중치)입니다."
    }

# ==============================================================================
# 도구 9: change_rate (두 시점 사이 변화량·변화율 - 막대)
# ==============================================================================
def change_rate(df, reference_period, base_period=None, label_column=None, n=10, exclude_aggregates=True):
    """
    두 시점(예: 2014년과 2024년) 사이의 절대 변화량(%p)과 변화율(%)을 계산하여 최대 증가 항목을 추출합니다.
    (공통 규칙: 기준 시점 reference_period 필수)
    """
    if not reference_period or str(reference_period).strip() == "":
        raise ValueError("change_rate 도구는 기준 시점(reference_period, 종료 시점)이 필수입니다.")

    ref_str = str(reference_period).strip()
    year_cols = find_year_columns(df)

    # 시작 시점 자동 결정 (기본값: 10년 전 또는 5년 전)
    if not base_period or str(base_period).strip() == "":
        if ref_str in year_cols:
            curr_idx = year_cols.index(ref_str)
            base_idx = max(0, curr_idx - 10) if curr_idx >= 10 else 0
            base_period = year_cols[base_idx]
        else:
            raise ValueError("비교할 시작 시점(base_period)을 지정해 주세요.")

    base_str = str(base_period).strip()
    if ref_str not in df.columns or base_str not in df.columns:
        raise ValueError(f"시점 열 '{base_str}' 또는 '{ref_str}'이 데이터셋에 존재하지 않습니다.")

    col = get_text_label_column(df, label_column)
    working_df = df.copy()
    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df, col)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    working_df[base_str] = pd.to_numeric(working_df[base_str], errors="coerce")
    working_df[ref_str] = pd.to_numeric(working_df[ref_str], errors="coerce")
    valid_df = working_df.dropna(subset=[base_str, ref_str]).copy()

    null_diff = len(working_df) - len(valid_df)
    if null_diff > 0:
        rows_excluded += null_diff
        exclusion_parts.append(f"두 시점 중 결측치 {null_diff}건 제외")

    if valid_df.empty:
        raise ValueError(f"{base_str}년과 {ref_str}년 모두 데이터가 존재하는 행이 없습니다.")

    # 절대 변화량(%p) 및 변화율(%)
    valid_df["diff_abs"] = valid_df[ref_str] - valid_df[base_str]
    valid_df["diff_pct"] = np.where(
        valid_df[base_str] > 0,
        ((valid_df[ref_str] - valid_df[base_str]) / valid_df[base_str]) * 100,
        np.nan
    )

    n = max(1, int(n))
    top_gainers = valid_df.sort_values(by="diff_abs", ascending=False).head(n)

    chart_labels = [str(x) for x in top_gainers[col].tolist()]
    chart_values = [sanitize_value(x) for x in top_gainers["diff_abs"].tolist()]

    records = []
    for _, r in top_gainers.iterrows():
        records.append({
            "label": str(r[col]),
            "base_val": sanitize_value(r[base_str]),
            "ref_val": sanitize_value(r[ref_str]),
            "diff_abs": sanitize_value(r["diff_abs"]),
            "diff_pct": sanitize_value(r["diff_pct"])
        })

    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "change_rate",
        "result": {
            "base_period": base_str,
            "reference_period": ref_str,
            "top_gainers": records,
            "chart_data": {
                "type": "bar",
                "labels": chart_labels,
                "values": chart_values
            }
        },
        "reference_period": f"{base_str}년 대비 {ref_str}년 변화량",
        "rows_used": len(valid_df),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [col, base_str, ref_str],
        "unit": "%p (포인트 변화량)",
        "cautions": "과거 수치가 극히 낮았던 국가는 소폭의 증가로도 % 변화율이 과도하게 커질 수 있으므로 %p(절대 증가폭)를 함께 보아야 합니다."
    }

# ==============================================================================
# 도구 10: distribution (구간별 분포 - 히스토그램)
# ==============================================================================
def distribution(df, reference_period, bins=10, value_column=None, exclude_aggregates=True):
    """
    특정 기준 시점의 데이터 값들이 어느 구간에 집중되어 있는지 빈도 분포를 산출합니다.
    (공통 규칙: 기준 시점 reference_period 필수)
    """
    if not reference_period or str(reference_period).strip() == "":
        raise ValueError("distribution 도구는 기준 시점(reference_period)이 필수입니다.")

    ref_str = str(reference_period).strip()
    target_col = value_column if (value_column and value_column in df.columns) else ref_str
    if target_col not in df.columns:
        raise ValueError(f"지정한 기준 시점 열 '{target_col}'이 데이터셋에 존재하지 않습니다.")

    working_df = df.copy()
    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    series = pd.to_numeric(working_df[target_col], errors="coerce").dropna()
    null_diff = len(working_df) - len(series)
    if null_diff > 0:
        rows_excluded += null_diff
        exclusion_parts.append(f"{ref_str}년 결측치 {null_diff}건 제외")

    if len(series) == 0:
        raise ValueError(f"기준 시점 '{ref_str}'에 유효한 수치 데이터가 없습니다.")

    bins = max(3, min(20, int(bins)))
    counts, bin_edges = np.histogram(series, bins=bins)

    bin_labels = []
    bin_details = []
    for i in range(len(counts)):
        b_start = round(float(bin_edges[i]), 1)
        b_end = round(float(bin_edges[i+1]), 1)
        label_text = f"{b_start}~{b_end}%"
        bin_labels.append(label_text)
        bin_details.append({
            "range": label_text,
            "count": int(counts[i]),
            "ratio": round(int(counts[i]) / len(series), 4)
        })

    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "distribution",
        "result": {
            "bins": bin_details,
            "chart_data": {
                "type": "bar",
                "labels": bin_labels,
                "values": [int(c) for c in counts]
            }
        },
        "reference_period": f"{ref_str}년 단일 시점",
        "rows_used": len(series),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [target_col],
        "unit": "개국 (구간별 빈도)",
        "cautions": "구간 수(bins)를 어떻게 설정하느냐에 따라 분포의 시각적 형태가 다소 달라 보일 수 있습니다."
    }

# ==============================================================================
# 도구 11: correlation_scatter (두 숫자 열 상관계수 - 산점도)
# ==============================================================================
def correlation_scatter(df, reference_period, col_x=None, col_y=None, label_column=None, exclude_aggregates=True):
    """
    두 수치형 열(예: 10년 전 보급률 vs 현재 보급률) 간의 피어슨 상관계수와 산점도 데이터를 산출합니다.
    (공통 규칙: 기준 시점 reference_period 필수, 상관관계!=인과관계 주의사항 명시)
    """
    if not reference_period or str(reference_period).strip() == "":
        raise ValueError("correlation_scatter 도구는 기준 시점(reference_period)이 필수입니다.")

    ref_str = str(reference_period).strip()
    year_cols = find_year_columns(df)

    # col_y 기본값: reference_period
    if not col_y or col_y not in df.columns:
        col_y = ref_str
    # col_x 기본값: 10년 전 연도 또는 다른 수치 열
    if not col_x or col_x not in df.columns:
        if ref_str in year_cols:
            curr_idx = year_cols.index(ref_str)
            col_x = year_cols[max(0, curr_idx - 10)]
        else:
            num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != col_y]
            col_x = num_cols[0] if num_cols else col_y

    col = get_text_label_column(df, label_column)
    working_df = df.copy()
    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df, col)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    working_df[col_x] = pd.to_numeric(working_df[col_x], errors="coerce")
    working_df[col_y] = pd.to_numeric(working_df[col_y], errors="coerce")
    valid_df = working_df.dropna(subset=[col_x, col_y]).copy()

    null_diff = len(working_df) - len(valid_df)
    if null_diff > 0:
        rows_excluded += null_diff
        exclusion_parts.append(f"두 열 중 결측치 {null_diff}건 제외")

    if len(valid_df) < 3:
        raise ValueError("상관계수를 계산하기 위한 유효 데이터 쌍이 부족합니다 (최소 3건 필요).")

    r = float(valid_df[col_x].corr(valid_df[col_y]))

    scatter_points = []
    for _, row in valid_df.iterrows():
        scatter_points.append({
            "x": sanitize_value(row[col_x]),
            "y": sanitize_value(row[col_y]),
            "label": str(row[col])
        })

    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "correlation_scatter",
        "result": {
            "col_x": col_x,
            "col_y": col_y,
            "correlation_coefficient": sanitize_value(r),
            "scatter_points": scatter_points[:100],
            "chart_data": {
                "type": "scatter",
                "datasets": [{
                    "label": f"{col_x} vs {col_y}",
                    "data": [{"x": p["x"], "y": p["y"]} for p in scatter_points]
                }]
            }
        },
        "reference_period": f"{ref_str}년 기준 ({col_x}와 비교)",
        "rows_used": len(valid_df),
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [col, col_x, col_y],
        "unit": "피어슨 상관계수 (-1.0 ~ 1.0)",
        "cautions": "**상관관계는 인과관계가 아닙니다.** 두 변수 간에 밀접한 상관성이 관찰되더라도 이것이 한쪽이 다른 쪽을 유발했다는 직접적 인과관계를 입증하지 않습니다."
    }

# ==============================================================================
# 도구 12: compare_one_vs_all (특정 항목 vs 전체 평균·중앙값 - 강조 막대)
# ==============================================================================
def compare_one_vs_all(df, reference_period, target_item="Korea, Rep.", value_column=None, label_column=None, exclude_aggregates=True):
    """
    특정 1개 국가(예: 대한민국)의 수치를 전체 국가의 대표값(평균, 중앙값, 최댓값, 최솟값)과 비교합니다.
    (공통 규칙: 기준 시점 reference_period 필수)
    """
    if not reference_period or str(reference_period).strip() == "":
        raise ValueError("compare_one_vs_all 도구는 기준 시점(reference_period)이 필수입니다.")

    ref_str = str(reference_period).strip()
    target_col = value_column if (value_column and value_column in df.columns) else ref_str
    if target_col not in df.columns:
        raise ValueError(f"지정한 기준 시점 열 '{target_col}'이 데이터셋에 존재하지 않습니다.")

    col = get_text_label_column(df, label_column)
    working_df = df.copy()
    rows_excluded = 0
    exclusion_parts = []

    if exclude_aggregates:
        working_df, excluded_idx = filter_aggregates_df(working_df, col)
        if excluded_idx:
            rows_excluded += len(excluded_idx)
            exclusion_parts.append(f"집계 행 {len(excluded_idx)}건 제외")

    working_df[target_col] = pd.to_numeric(working_df[target_col], errors="coerce")
    valid_df = working_df.dropna(subset=[target_col]).copy()

    null_diff = len(working_df) - len(valid_df)
    if null_diff > 0:
        rows_excluded += null_diff
        exclusion_parts.append(f"{ref_str}년 결측치 {null_diff}건 제외")

    # 대상 항목 값 찾기
    item_row = valid_df[valid_df[col].astype(str) == str(target_item)]
    if item_row.empty:
        # 혹시 대소문자나 축약어 고려 검색
        item_row = valid_df[valid_df[col].astype(str).str.contains(str(target_item).split(",")[0], case=False, na=False)]
        if item_row.empty:
            raise ValueError(f"비교 대상 항목 '{target_item}'을 {ref_str}년 유효 데이터에서 찾을 수 없습니다.")

    target_name = str(item_row[col].values[0])
    target_val = float(item_row[target_col].values[0])

    # 순위 계산 (1위부터)
    sorted_df = valid_df.sort_values(by=target_col, ascending=False).reset_index(drop=True)
    rank = int(sorted_df[sorted_df[col] == target_name].index[0]) + 1
    total_valid = len(sorted_df)

    mean_val = float(valid_df[target_col].mean())
    median_val = float(valid_df[target_col].median())
    max_val = float(valid_df[target_col].max())
    min_val = float(valid_df[target_col].min())

    chart_labels = [f"{target_name} (선택)", "전체 중앙값", "전체 평균", "전체 최고", "전체 최저"]
    chart_values = [
        sanitize_value(target_val),
        sanitize_value(median_val),
        sanitize_value(mean_val),
        sanitize_value(max_val),
        sanitize_value(min_val)
    ]

    exclusion_reason = ", ".join(exclusion_parts) if exclusion_parts else "제외 항목 없음"

    return {
        "tool": "compare_one_vs_all",
        "result": {
            "target_item": target_name,
            "target_value": sanitize_value(target_val),
            "rank": rank,
            "total_count": total_valid,
            "percentile": round(((total_valid - rank + 1) / total_valid) * 100, 1),
            "mean": sanitize_value(mean_val),
            "median": sanitize_value(median_val),
            "diff_from_median": sanitize_value(target_val - median_val),
            "diff_from_mean": sanitize_value(target_val - mean_val),
            "chart_data": {
                "type": "bar",
                "labels": chart_labels,
                "values": chart_values,
                "highlight_index": 0
            }
        },
        "reference_period": f"{ref_str}년 단일 시점",
        "rows_used": total_valid,
        "rows_excluded": rows_excluded,
        "exclusion_reason": exclusion_reason,
        "columns_used": [col, target_col],
        "unit": "% (인터넷 사용률)",
        "cautions": f"{target_name}의 상대적 위상을 나타내기 위해 전체 {total_valid}개국과의 단순 수치 차이를 비교한 통계입니다."
    }

# ==============================================================================
# 도구 메타데이터 카탈로그 (Gemini 제안 및 API 유효성 검증용)
# ==============================================================================
TOOL_CATALOG = [
    {
        "name": "reshape_wide_to_long",
        "name_ko": "데이터 세로형(Tidy) 변환",
        "description": "연도 열이 가로로 펼쳐진 Wide 데이터를 분석 표준인 세로형(Tidy) 데이터로 변환합니다.",
        "params": ["id_vars", "value_name", "var_name", "exclude_aggregates"],
        "requires_reference_period": False
    },
    {
        "name": "quality_report",
        "name_ko": "데이터셋 품질 진단 리포트",
        "description": "데이터셋 전체의 결측치, 중복 행, 열 이름 이상 여부 및 데이터 타입을 진단합니다.",
        "params": ["exclude_aggregates"],
        "requires_reference_period": False
    },
    {
        "name": "year_coverage",
        "name_ko": "연도별 충실도 분석",
        "description": "연도별 유효 데이터 개수를 집계하고 결측치가 적은 최적 권장 기준연도를 제안합니다.",
        "params": ["exclude_aggregates"],
        "requires_reference_period": False
    },
    {
        "name": "detect_aggregates",
        "name_ko": "집계 및 그룹 행 탐지",
        "description": "World, Arab World 등 개별 국가가 아닌 대륙 및 소득 그룹 집계 행을 탐지합니다.",
        "params": ["label_column"],
        "requires_reference_period": False
    },
    {
        "name": "describe_numeric",
        "name_ko": "요약 통계량 산출",
        "description": "수치 열(또는 기준연도 열)의 평균, 중앙값, 분산 등 요약 통계량을 산출합니다.",
        "params": ["value_column", "reference_period", "exclude_aggregates"],
        "requires_reference_period": False
    },
    {
        "name": "trend_line",
        "name_ko": "시계열 추세선 분석",
        "description": "선택한 주요 국가들의 연도별 시계열 변화 추이를 선 차트로 시각화합니다.",
        "params": ["items", "label_column", "start_year", "end_year", "exclude_aggregates"],
        "requires_reference_period": False
    },
    {
        "name": "top_bottom_n",
        "name_ko": "상위/하위 N개국 순위 분석",
        "description": "단일 기준 시점(예: 2024년) 기준 상위 또는 하위 N개 국가를 추출하여 순위 막대 차트를 생성합니다.",
        "params": ["reference_period", "value_column", "label_column", "n", "mode", "exclude_aggregates"],
        "requires_reference_period": True
    },
    {
        "name": "group_summary",
        "name_ko": "대륙/소득군 그룹별 비교",
        "description": "지역(대륙)이나 소득 그룹별 평균 및 중앙값을 집계하여 비교 막대 차트를 생성합니다.",
        "params": ["reference_period", "group_column", "value_column", "agg_func", "exclude_aggregates"],
        "requires_reference_period": True
    },
    {
        "name": "change_rate",
        "name_ko": "기간별 증감량 및 변화율 분석",
        "description": "두 시점(예: 2014년 vs 2024년) 사이의 절대 증가량(%p)과 변화율(%)을 계산하여 최대 성장 국가를 추출합니다.",
        "params": ["reference_period", "base_period", "label_column", "n", "exclude_aggregates"],
        "requires_reference_period": True
    },
    {
        "name": "distribution",
        "name_ko": "구간별 수치 빈도 분포",
        "description": "기준 시점의 수치들이 어떤 구간에 얼마나 집중되어 있는지 빈도 분포(히스토그램)를 작성합니다.",
        "params": ["reference_period", "bins", "value_column", "exclude_aggregates"],
        "requires_reference_period": True
    },
    {
        "name": "correlation_scatter",
        "name_ko": "상관관계 산점도 분석",
        "description": "두 시점 또는 두 수치 열 간의 피어슨 상관계수와 산점도(Scatter) 데이터를 계산합니다.",
        "params": ["reference_period", "col_x", "col_y", "label_column", "exclude_aggregates"],
        "requires_reference_period": True
    },
    {
        "name": "compare_one_vs_all",
        "name_ko": "특정 국가 vs 전체 비교",
        "description": "특정 1개 국가(예: 대한민국)의 수치와 순위를 전체 국가의 대표값(중앙값, 평균)과 비교 강조합니다.",
        "params": ["reference_period", "target_item", "value_column", "label_column", "exclude_aggregates"],
        "requires_reference_period": True
    }
]
