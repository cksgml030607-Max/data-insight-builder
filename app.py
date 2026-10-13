import os
import io
import csv
import re
import json
import inspect
import logging
import numpy as np
import pandas as pd
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv
from google import genai
from google.genai import types

import tools

# .env 환경변수 로드
load_dotenv()

# 로깅 설정 (print() 대신 logging 모듈 사용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("data-insight-builder")

app = Flask(__name__)

# 업로드 최대 용량 설정 (기본값 10MB)
max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "10"))
app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

# 메모리 내 1개 데이터셋 및 실행 결과 보관용 전역 변수
# (디스크에 영구 저장하지 않으며 서버 재시작 시 초기화됨)
CURRENT_DATASET = {}

def detect_header_row(sample_lines):
    """
    앞쪽 최대 25줄을 스캔하여 실제 테이블의 헤더(열 이름) 행 인덱스를 찾습니다.
    """
    sample_rows = list(csv.reader(sample_lines[:25]))
    if not sample_rows:
        return 0
    best_idx = 0
    max_cols = 0
    for idx, row in enumerate(sample_rows):
        non_empty = len([c for c in row if c.strip()])
        if non_empty > max_cols:
            max_cols = non_empty
            best_idx = idx
    return best_idx

def get_indicator_metadata():
    """
    data 디렉터리 내에 지표 메타데이터 파일이 존재하는 경우 출처와 정의를 추출합니다.
    """
    for root, _, files in os.walk("data"):
        for f in files:
            if f.startswith("Metadata_Indicator") and f.endswith(".csv"):
                try:
                    p = os.path.join(root, f)
                    with open(p, "r", encoding="utf-8-sig") as fp:
                        r = list(csv.reader(fp))
                        if len(r) > 1:
                            return {
                                "code": r[1][0] if len(r[1]) > 0 else "IT.NET.USER.ZS",
                                "name": r[1][1] if len(r[1]) > 1 else "Individuals using the Internet (% of population)",
                                "note": r[1][2] if len(r[1]) > 2 else "Internet users are individuals who have used the Internet (from any location) in the last 3 months.",
                                "source": r[1][3] if len(r[1]) > 3 else "International Telecommunication Union (ITU)"
                            }
                except Exception:
                    pass
    return {
        "code": "IT.NET.USER.ZS",
        "name": "인터넷 이용자 비율 (% of population)",
        "note": "최근 3개월 이내에 어떤 기기(컴퓨터, 스마트폰 등)로든 인터넷을 사용한 사람의 비율",
        "source": "세계은행 (World Bank) / 국제전기통신연합 (ITU)"
    }

def diagnose_dataframe(df, filename, file_size, chosen_encoding, skipped_rows):
    """
    Pandas 데이터프레임을 정밀 분석하여 품질, 연도별 충실도, 집계 행 감지 및 경고를 생성합니다.
    """
    total_rows = len(df)
    total_cols = len(df.columns)
    column_names = [str(c) for c in df.columns]
    
    dtypes = {str(c): str(df[c].dtype) for c in df.columns}
    numeric_columns = [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    text_columns = [str(c) for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    year_columns = [str(c) for c in df.columns if re.match(r"^(19|20)\d{2}$", str(c).strip())]

    missing_values = {
        str(c): {
            "count": int(df[c].isna().sum()),
            "ratio": round(int(df[c].isna().sum()) / total_rows, 4) if total_rows > 0 else 0.0
        }
        for c in df.columns
    }
    duplicate_rows = int(df.duplicated().sum())

    unnamed_columns = [str(c) for c in df.columns if str(c).startswith("Unnamed:") or str(c).strip() == ""]
    all_empty_columns = [str(c) for c in df.columns if df[c].isna().all()]

    year_coverage = {}
    recommended_year = None
    if year_columns:
        for y in year_columns:
            filled = int(df[y].notna().sum())
            year_coverage[str(y)] = {
                "filled_count": filled,
                "total": total_rows,
                "ratio": round(filled / total_rows, 4) if total_rows > 0 else 0.0
            }
        max_filled = max((v["filled_count"] for v in year_coverage.values()), default=0)
        threshold = max_filled * 0.8
        valid_years = [y for y, v in year_coverage.items() if v["filled_count"] >= threshold]
        recommended_year = valid_years[-1] if valid_years else year_columns[-1]

    agg_keywords = [
        "world", "oecd", "euro area", "european union", "high income",
        "low income", "income", "area", "total", "dividend", "small states"
    ]
    aggregate_candidates = []
    target_text_col = text_columns[0] if text_columns else None
    if target_text_col:
        for idx, val in df[target_text_col].items():
            if any(kw in str(val).lower() for kw in agg_keywords):
                aggregate_candidates.append({
                    "index": int(idx),
                    "label": str(val)
                })

    warnings = []
    if unnamed_columns:
        warnings.append(f"이름이 없는 Unnamed 열이 {len(unnamed_columns)}개 감지되었습니다 ({', '.join(unnamed_columns[:3])} 등).")
    if all_empty_columns:
        warnings.append(f"모든 행이 완전히 비어 있는 열이 {len(all_empty_columns)}개 있습니다.")
    if duplicate_rows > 0:
        warnings.append(f"중복된 데이터 행이 {duplicate_rows}건 발견되었습니다.")
    if aggregate_candidates:
        warnings.append(f"전체 평균/합계 왜곡을 일으킬 수 있는 집계 행 후보가 {len(aggregate_candidates)}건 발견되었습니다 (예: {aggregate_candidates[0]['label']}).")
    if year_columns and recommended_year and year_columns[-1] != recommended_year:
        last_y = year_columns[-1]
        last_y_filled = year_coverage[last_y]["filled_count"]
        rec_y_filled = year_coverage[recommended_year]["filled_count"]
        warnings.append(
            f"최신 열({last_y})은 데이터가 {last_y_filled}건으로 급감하여 결측치가 심합니다. "
            f"데이터가 충분히 모인 {recommended_year}년({rec_y_filled}건)을 기준 시점으로 권장합니다."
        )

    preview_df = df.head(10).replace({np.nan: None})
    preview = preview_df.to_dict(orient="records")

    return {
        "status": "success",
        "filename": filename,
        "file_size": file_size,
        "encoding": chosen_encoding,
        "skipped_rows": skipped_rows,
        "rows": total_rows,
        "columns": total_cols,
        "column_names": column_names,
        "dtypes": dtypes,
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "year_columns": year_columns,
        "missing_values": missing_values,
        "duplicate_rows": duplicate_rows,
        "unnamed_columns": unnamed_columns,
        "all_empty_columns": all_empty_columns,
        "year_coverage": year_coverage,
        "recommended_year": recommended_year,
        "aggregate_candidates": aggregate_candidates,
        "preview": preview,
        "warnings": warnings,
        "notice": "데이터셋은 서버 메모리에만 임시 보관되며, 서버 재시작 시 초기화됩니다."
    }

@app.before_request
def log_request_info():
    logger.info(f"[REQUEST] {request.method} {request.path}")

@app.after_request
def log_response_info(response):
    logger.info(f"[RESPONSE] status={response.status_code}")
    return response

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/health", methods=["GET"])
def health():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    has_api_key = bool(api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    return jsonify({
        "status": "ok",
        "api_key_configured": has_api_key,
        "model": model_name
    })

@app.route("/inspect", methods=["POST"])
def inspect_file():
    global CURRENT_DATASET
    
    if "file" not in request.files:
        logger.warning("[ERROR] 파일이 전송되지 않았습니다.")
        return jsonify({"error": "업로드할 CSV 파일을 선택해 주세요."}), 400
        
    file = request.files["file"]
    if not file or file.filename.strip() == "":
        logger.warning("[ERROR] 파일명이 비어 있습니다.")
        return jsonify({"error": "파일을 선택해 주세요."}), 400
        
    filename = file.filename
    if not filename.lower().endswith(".csv"):
        logger.warning(f"[ERROR] 지원하지 않는 파일 형식: {filename}")
        return jsonify({"error": "CSV 파일(.csv)만 업로드할 수 있습니다."}), 400

    raw_bytes = file.read()
    file_size = len(raw_bytes)
    logger.info(f"[FILE] name={filename} size={file_size} bytes")

    if file_size == 0:
        logger.warning("[ERROR] 빈 파일입니다.")
        return jsonify({"error": "내용이 비어 있는 빈 파일(0 bytes)입니다."}), 400

    candidate_encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    decoded_text = None
    chosen_encoding = None

    for enc in candidate_encodings:
        try:
            decoded_text = raw_bytes.decode(enc)
            chosen_encoding = enc
            logger.info(f"[ENCODING] {enc} 성공")
            break
        except UnicodeDecodeError:
            logger.info(f"[ENCODING] {enc} 실패, 다음 인코딩 시도")
            continue

    if chosen_encoding is None:
        logger.error("[ERROR] 모든 인코딩(utf-8-sig, utf-8, cp949, euc-kr) 시도 실패")
        return jsonify({"error": "지원하는 문자 인코딩(UTF-8, CP949, EUC-KR)으로 파일을 디코딩하지 못했습니다."}), 400

    lines = decoded_text.splitlines()
    skipped_rows = detect_header_row(lines)
    logger.info(f"[HEADER] 헤더 줄 감지 결과 (건너뛴 줄 수={skipped_rows})")

    try:
        df = pd.read_csv(
            io.BytesIO(raw_bytes),
            skiprows=skipped_rows,
            encoding=chosen_encoding
        )
        logger.info(f"[CSV] parsing 완료 rows={len(df)} columns={len(df.columns)}")
    except Exception as e:
        logger.error(f"[ERROR] CSV 파싱 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"CSV 파일 파싱 중 오류가 발생했습니다: {str(e)}"}), 400

    report = diagnose_dataframe(df, filename, file_size, chosen_encoding, skipped_rows)
    logger.info(f"[DIAGNOSE] 진단 완료 warnings={len(report['warnings'])}")

    CURRENT_DATASET.clear()
    CURRENT_DATASET.update({
        "filename": filename,
        "file_size": file_size,
        "encoding": chosen_encoding,
        "skipped_rows": skipped_rows,
        "df": df,
        "report": report
    })

    return jsonify(report)

@app.route("/suggest", methods=["POST"])
def suggest_analyses():
    global CURRENT_DATASET
    
    if not CURRENT_DATASET or "report" not in CURRENT_DATASET:
        logger.warning("[ERROR] 진단된 데이터셋이 없습니다.")
        return jsonify({"error": "분석을 제안할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400
        
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 키를 입력해 주세요."}), 400
        
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    report = CURRENT_DATASET["report"]
    rec_year = report.get("recommended_year", "2024")
    
    diagnosis_summary = {
        "filename": report["filename"],
        "total_rows": report["rows"],
        "total_columns": report["columns"],
        "recommended_year": rec_year,
        "year_columns_range": [report["year_columns"][0], report["year_columns"][-1]] if report.get("year_columns") else [],
        "text_columns": report.get("text_columns", [])[:3],
        "numeric_columns": report.get("numeric_columns", [])[:5],
        "aggregate_candidates_count": len(report.get("aggregate_candidates", [])),
        "warnings": report.get("warnings", [])
    }
    
    catalog_json = json.dumps(tools.TOOL_CATALOG, ensure_ascii=False, indent=2)
    summary_json = json.dumps(diagnosis_summary, ensure_ascii=False, indent=2)
    
    prompt = f"""
당신은 교육용 데이터 분석 보조 AI입니다.
사용자가 업로드한 CSV 데이터의 상태 진단 요약을 보고, 제공된 [도구 카탈로그]에서 실제로 실행 가능한 최적의 분석 3~5개를 골라 제안하십시오.

[데이터 진단 요약]
{summary_json}

[도구 카탈로그 (이 목록에 있는 도구만 제안 가능)]
{catalog_json}

[절대 규칙]
1. 도구 카탈로그에 등록된 'name'만 제안할 수 있습니다. 카탈로그에 없는 도구는 절대 제안하지 마십시오.
2. 데이터셋에 없는 열 이름은 파라미터로 지정하지 마십시오.
3. 기준 시점(reference_period)이 필요한 도구는 권장 기준연도('{rec_year}')를 기본으로 사용하십시오.
4. exclude_aggregates는 반드시 true로 설정하십시오.
5. 당신은 직접 계산을 하지 않습니다. Pandas가 실행할 도구와 파라미터만 지정하십시오.
6. 제안 개수는 3개 이상 5개 이하로 하십시오.
7. 반드시 아래의 순수 JSON 포맷으로만 응답하십시오.

JSON 형식:
{{
  "suggestions": [
    {{
      "tool": "카탈로그에_있는_도구명",
      "params": {{
        "reference_period": "{rec_year}",
        "exclude_aggregates": true
      }},
      "reference_period": "{rec_year}",
      "why": "이 분석이 이 데이터에서 의미 있는 이유 (중학생도 이해할 수 있게 쉬운 설명)",
      "caution": "해석할 때 주의할 점"
    }}
  ]
}}
"""

    logger.info(f"[AI] suggest 요청 시작 (model={model_name})")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        logger.info("[AI] suggest 응답 수신")
        
        raw_text = response.text.strip()
        parsed = json.loads(raw_text)
        
        allowed_tools = {t["name"] for t in tools.TOOL_CATALOG}
        valid_suggestions = []
        for item in parsed.get("suggestions", []):
            if item.get("tool") in allowed_tools:
                valid_suggestions.append(item)
                
        logger.info(f"[AI] JSON 파싱 결과 (유효 제안 수={len(valid_suggestions)})")
        
        return jsonify({
            "status": "success",
            "model": model_name,
            "suggestions": valid_suggestions
        })
    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] Gemini 응답 JSON 파싱 실패: {str(je)}", exc_info=True)
        return jsonify({"error": "AI의 응답을 JSON 형식으로 해석하지 못했습니다."}), 500
    except Exception as e:
        logger.error(f"[ERROR] Gemini suggest 호출 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"AI 분석 제안 생성 중 오류가 발생했습니다: {str(e)}"}), 500

@app.route("/run", methods=["POST"])
def run_analysis():
    global CURRENT_DATASET
    
    if not CURRENT_DATASET or "df" not in CURRENT_DATASET:
        logger.warning("[ERROR] 실행할 데이터셋이 메모리에 없습니다.")
        return jsonify({"error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    tool_name = req_data.get("tool")
    if not tool_name:
        logger.warning("[ERROR] 실행할 도구명이 전달되지 않았습니다.")
        return jsonify({"error": "실행할 도구 이름(tool)을 지정해 주세요."}), 400

    catalog_map = {t["name"]: t for t in tools.TOOL_CATALOG}
    if tool_name not in catalog_map:
        logger.warning(f"[ERROR] 도구 목록에 없는 도구 요청: {tool_name}")
        return jsonify({"error": f"도구 목록에 존재하지 않는 도구입니다: '{tool_name}'"}), 400

    tool_meta = catalog_map[tool_name]
    func = getattr(tools, tool_name, None)
    if not callable(func):
        logger.error(f"[ERROR] tools 모듈에서 함수를 찾을 수 없음: {tool_name}")
        return jsonify({"error": f"도구 함수 '{tool_name}'을 호출할 수 없습니다."}), 500

    params = req_data.get("params", {})
    if not isinstance(params, dict):
        params = {}
    for k, v in req_data.items():
        if k not in ["tool", "params"] and k not in params:
            params[k] = v

    if tool_meta.get("requires_reference_period", False):
        ref_period = params.get("reference_period")
        if not ref_period or str(ref_period).strip() == "":
            logger.warning(f"[ERROR] {tool_name} 필수 파라미터(reference_period) 누락")
            return jsonify({
                "error": f"'{tool_name}' 도구는 기준 시점(reference_period)이 필수 입력 항목입니다."
            }), 400

    sig = inspect.signature(func)
    accepted_params = set(sig.parameters.keys())
    clean_kwargs = {k: v for k, v in params.items() if k in accepted_params}

    df = CURRENT_DATASET["df"]
    try:
        calc_result = func(df, **clean_kwargs)
        
        logger.info(
            f"[TOOL] {tool_name}, params={clean_kwargs}, "
            f"rows_used={calc_result.get('rows_used')}, rows_excluded={calc_result.get('rows_excluded')}"
        )

        CURRENT_DATASET["latest_run"] = {
            "tool": tool_name,
            "params": clean_kwargs,
            "result": calc_result
        }

        return jsonify({
            "status": "success",
            "data": calc_result
        })

    except ValueError as ve:
        logger.warning(f"[ERROR] 분석 실행 데이터 검증 실패: {str(ve)}")
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"[ERROR] 도구 실행 실패 ({tool_name}): {str(e)}", exc_info=True)
        return jsonify({"error": f"분석 도구 실행 중 오류가 발생했습니다: {str(e)}"}), 500

@app.route("/explain", methods=["POST"])
def explain_analysis():
    global CURRENT_DATASET

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 키를 입력해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    req_data = request.get_json(silent=True) or {}
    mode = str(req_data.get("mode", "B")).upper().strip()

    if mode not in ["A", "B"]:
        mode = "B"

    logger.info(f"[REQUEST] POST /explain (mode={mode})")

    try:
        client = genai.Client(api_key=api_key)

        # -------------------------------------------------------------
        # 모드 A (비교용, 의도적으로 허술하게):
        # 진단 요약만 전달하고 "이 데이터를 분석해서 보고서를 써줘"라고 요청.
        # Pandas 계산 결과를 주지 않는다.
        # -------------------------------------------------------------
        if mode == "A":
            if not CURRENT_DATASET or "report" not in CURRENT_DATASET:
                return jsonify({"error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400
            
            report = CURRENT_DATASET["report"]
            summary_info = {
                "filename": report["filename"],
                "total_rows": report["rows"],
                "total_columns": report["columns"],
                "columns": report["column_names"][:10]
            }
            prompt_a = f"""
당신은 AI 어시스턴트입니다. 아래 데이터 요약을 보고, 이 데이터를 자유롭게 분석하여 종합 보고서를 작성해 주십시오.

[데이터 요약]
{json.dumps(summary_info, ensure_ascii=False, indent=2)}
"""
            logger.info("[AI] explain 요청 시작 (모드 A)")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt_a,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            logger.info("[AI] explain 응답 수신 (모드 A)")
            return jsonify({
                "status": "success",
                "mode": "A",
                "model": model_name,
                "explanation": response.text
            })

        # -------------------------------------------------------------
        # 모드 B (정식):
        # Pandas가 계산한 결과(표, 기준시점, 제외 행 수)만 전달하고
        # 8대 규칙과 7단 마크다운 구조를 엄격히 지켜 해석.
        # -------------------------------------------------------------
        else:
            if not CURRENT_DATASET or "latest_run" not in CURRENT_DATASET:
                return jsonify({
                    "error": "해석할 계산 결과가 없습니다. 먼저 분석 도구를 실행(/run)해 주세요."
                }), 400

            run_info = CURRENT_DATASET["latest_run"]
            calc_result = run_info["result"]
            indicator_meta = get_indicator_metadata()

            calc_payload = {
                "tool": run_info["tool"],
                "reference_period": calc_result.get("reference_period"),
                "rows_used": calc_result.get("rows_used"),
                "rows_excluded": calc_result.get("rows_excluded"),
                "exclusion_reason": calc_result.get("exclusion_reason"),
                "columns_used": calc_result.get("columns_used"),
                "unit": calc_result.get("unit"),
                "cautions": calc_result.get("cautions"),
                "result": calc_result.get("result")
            }

            prompt_b = f"""
당신은 데이터 리터러시 교육 전문가입니다.
Pandas가 방금 계산을 마친 결과 데이터만 바탕으로 사실에 입각한 해석 보고서를 작성하십시오.

[계산 결과 데이터 (Pandas 연산 완료)]
{json.dumps(calc_payload, ensure_ascii=False, indent=2)}

[지표 정의 및 출처]
- 지표명: {indicator_meta.get('name')}
- 출처: {indicator_meta.get('source')}
- 공식 정의: {indicator_meta.get('note')}

[해석 작성 8대 원칙]
1. 제공된 계산 결과에 있는 숫자만 사용하십시오.
2. 직접 계산하거나 숫자를 추정/추측하지 마십시오.
3. 데이터에 없는 국가, 연도, 열을 임의로 언급하지 마십시오.
4. 기준 시점과 제외된 행 수 및 그 이유를 본문에 반드시 명시하십시오.
5. 상관관계를 인과관계로 표현하지 마십시오.
6. 지표의 정의와 출처를 보고서 앞부분(데이터 출처와 정의)에 명확히 표기하십시오.
7. 확인할 수 없는 것은 "이 데이터로는 확인할 수 없다"라고 솔직하게 쓰십시오.
8. 중학생도 이해할 수 있게 친절하고 명확하게 쓰되 사실적 정확성을 엄격히 유지하십시오.

[출력 형식]
반드시 아래 7개 마크다운 헤더 형식을 순서대로 정확히 지켜 작성하십시오:
## 무엇을 봤는가
## 데이터 출처와 정의
## 기준 시점과 제외된 항목
## 계산 결과
## 읽어낼 수 있는 것
## 이 데이터로는 알 수 없는 것
## 다음에 확인해볼 것
"""

            logger.info("[AI] explain 요청 시작 (모드 B)")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt_b,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            logger.info("[AI] explain 응답 수신 (모드 B)")

            CURRENT_DATASET["latest_explanation"] = response.text

            return jsonify({
                "status": "success",
                "mode": "B",
                "model": model_name,
                "explanation": response.text
            })

    except Exception as e:
        logger.error(f"[ERROR] Gemini explain 호출 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"AI 해석 생성 중 오류가 발생했습니다: {str(e)}"}), 500

@app.route("/query", methods=["POST"])
def query_natural_language():
    """
    사용자의 자연어 질문을 받아 도구 매핑 -> Pandas 연산 -> 사실 기반 답변을 생성합니다.
    """
    global CURRENT_DATASET
    
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 키를 입력해 주세요."}), 400

    if not CURRENT_DATASET or "df" not in CURRENT_DATASET:
        return jsonify({"error": "분석할 데이터셋이 없습니다. 먼저 CSV 파일을 업로드해 주세요."}), 400

    req_data = request.get_json(silent=True) or {}
    user_query = req_data.get("query", "").strip()
    if not user_query:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    df = CURRENT_DATASET["df"]
    diagnostics = CURRENT_DATASET.get("diagnostics", {})
    recommended_year = diagnostics.get("recommended_year", "2024")
    indicator = CURRENT_DATASET.get("indicator", {})
    
    # 1. 도구 매핑 프롬프트
    catalog_summary = []
    for t in tools.TOOL_CATALOG:
        catalog_summary.append({
            "name": t["name"],
            "name_ko": t.get("name_ko", t["name"]),
            "description": t["description"],
            "requires_reference_period": t.get("requires_reference_period", False),
            "requires_target_country": t.get("requires_target_country", False),
            "requires_countries": t.get("requires_countries", False)
        })

    tool_selection_prompt = f"""
당신은 데이터 분석 도구 매핑 전문가입니다.
사용자의 자연어 질문을 분석하여 가장 알맞은 1개의 분석 도구(tool)와 실행 매개변수(params)를 선정하십시오.

[데이터셋 정보]
- 지표명: {indicator.get('name', 'IT.NET.USER.ZS')}
- 권장 기준연도: {recommended_year}
- 연도 컬럼: 1960 ~ 2025 (2024년이 가장 결측치가 적은 최신 연도)
- 국가명 형식: World Bank 공식 영문명 (예: 한국은 'Korea, Rep.', 미국은 'United States', 일본은 'Japan', 중국은 'China', 독일은 'Germany', 영국은 'United Kingdom', 프랑스는 'France')

[사용 가능한 도구 카탈로그]
{json.dumps(catalog_summary, ensure_ascii=False, indent=2)}

[사용자의 질문]
"{user_query}"

[도구 매핑 원칙]
1. 특정 국가의 순위나 특정 국가와 전체 비교를 묻는 경우: compare_one_vs_all (target_country: World Bank 영문명, reference_period: "{recommended_year}")
2. 상위/하위 N개국, 최고/최저 국가를 묻는 경우: top_bottom_n (n: 5 또는 10, order: "top" 또는 "bottom", reference_period: "{recommended_year}")
3. 연도별 변화 추이, 시간에 따른 변화, 특정 국가들의 추세를 묻는 경우: trend_line (countries: ["Korea, Rep.", ...] 또는 빈 배열)
4. 전 세계 평균, 중앙값, 최빈값, 분포를 묻는 경우: distribution 또는 describe_numeric (reference_period: "{recommended_year}")
5. 대륙별/소득수준별 차이를 묻는 경우: group_summary (reference_period: "{recommended_year}")
6. 전년 대비 증감률을 묻는 경우: change_rate (base_period: "2023", target_period: "2024")
7. 항상 exclude_aggregates는 true로 설정하십시오.
8. 연도가 명시되지 않은 질문은 반드시 권장 연도 "{recommended_year}"를 reference_period로 사용하십시오.

반드시 아래 JSON 형식으로만 응답하십시오:
{{
  "tool": "도구명 (예: compare_one_vs_all, top_bottom_n, trend_line 등)",
  "params": {{
    "reference_period": "{recommended_year}",
    "exclude_aggregates": true
  }}
}}
"""
    logger.info(f"[REQUEST] POST /query (query='{user_query}')")
    try:
        client = genai.Client(api_key=api_key)
        resp1 = client.models.generate_content(
            model=model_name,
            contents=tool_selection_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        parsed_plan = json.loads(resp1.text.strip())
        tool_name = parsed_plan.get("tool", "top_bottom_n")
        params = parsed_plan.get("params", {})
        
        # 유효한 도구인지 검증 (없으면 top_bottom_n 대체)
        catalog_map = {t["name"]: t for t in tools.TOOL_CATALOG}
        if tool_name not in catalog_map:
            tool_name = "top_bottom_n"
            params = {"reference_period": recommended_year, "n": 10, "order": "top", "exclude_aggregates": True}

        tool_meta = catalog_map[tool_name]
        func = getattr(tools, tool_name)

        # 도구 실행에 필요한 인수 추출
        sig = inspect.signature(func)
        accepted_params = set(sig.parameters.keys())
        clean_kwargs = {k: v for k, v in params.items() if k in accepted_params}
        if "reference_period" in accepted_params and "reference_period" not in clean_kwargs:
            clean_kwargs["reference_period"] = recommended_year
        if "exclude_aggregates" in accepted_params and "exclude_aggregates" not in clean_kwargs:
            clean_kwargs["exclude_aggregates"] = True

        logger.info(f"[QUERY] Pandas 연산 실행 도구={tool_name}, kwargs={clean_kwargs}")
        calc_result = func(df, **clean_kwargs)
        
        # latest_run 업데이트 (Step 3, 4와 자연스럽게 연결)
        CURRENT_DATASET["latest_run"] = {
            "tool": tool_name,
            "params": clean_kwargs,
            "result": calc_result
        }

        # 2. 계산 결과를 바탕으로 답변 생성 프롬프트
        answer_prompt = f"""
당신은 데이터 분석 리터러시 튜터입니다.
사용자의 질문에 대해, 실제로 계산된 Pandas 수치 결과만을 바탕으로 친절하고 명쾌하게 답변하십시오.

[사용자의 질문]
"{user_query}"

[수행된 분석 도구]
{tool_meta['name_ko']} ({tool_name})

[실제 Pandas 계산 결과]
{json.dumps(calc_result, ensure_ascii=False, indent=2)}

[답변 작성 지침]
1. 반드시 위 계산 결과에 실제로 존재하는 숫자와 국가명만 인용하십시오.
2. 질문에 대한 핵심 결론을 첫 문장에서 바로 명쾌하게 제시하십시오.
3. 숫자는 이해하기 쉽게 포맷팅(예: 97.4%, 1위)하여 가독성을 높이십시오.
4. 기준 연도와 분석 대상(집계행 제외 여부 등)을 간략히 언급하여 데이터 신뢰성을 부여하십시오.
5. 마크다운 문법(굵은 글씨, 글머리 기호 등)을 사용하여 깔끔하게 작성하십시오.
"""
        resp2 = client.models.generate_content(
            model=model_name,
            contents=answer_prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        answer_text = resp2.text.strip()

        unit = indicator.get("unit", "%")

        return jsonify({
            "status": "success",
            "query": user_query,
            "tool": tool_name,
            "tool_name_ko": tool_meta.get("name_ko", tool_name),
            "params": clean_kwargs,
            "answer": answer_text,
            "result": calc_result,
            "unit": unit
        })

    except Exception as e:
        logger.error(f"[ERROR] /query 처리 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"자연어 질문 분석 중 오류가 발생했습니다: {str(e)}"}), 500

@app.route("/chat", methods=["POST"])
def chat_followup():
    global CURRENT_DATASET
    
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[ERROR] GEMINI_API_KEY 미설정")
        return jsonify({"error": "Gemini API Key가 설정되지 않았습니다. .env 파일에 키를 입력해 주세요."}), 400

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    req_data = request.get_json(silent=True) or {}
    user_message = req_data.get("message", "").strip()
    history = req_data.get("history", [])

    if not user_message:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    run_info = CURRENT_DATASET.get("latest_run", {})
    calc_result = run_info.get("result", {})
    report_text = CURRENT_DATASET.get("latest_explanation", "")

    chat_prompt = f"""
당신은 친절하고 유능한 데이터 리터러시 교육 튜터입니다.
사용자는 방금 생성된 분석 결과 및 보고서에 대해 후속 질문을 하고 있습니다.

[이전 분석 보고서]
{report_text}

[Pandas 실제 연산 결과 데이터]
{json.dumps(calc_result, ensure_ascii=False, indent=2)}

[이전 대화 내역]
{json.dumps(history[-6:], ensure_ascii=False)}

[사용자의 이번 질문]
"{user_message}"

[답변 작성 지침]
1. 반드시 위 계산 결과와 보고서에 있는 사실만을 근거로 답변하십시오. 없는 수치를 거짓으로 꾸며내지 마십시오.
2. 사용자가 "쉽게 설명해줘" 또는 "중학생도 이해할 수 있게 설명해줘"라고 요청할 때는, 어려운 전문 용어를 싹 빼고 일상 속 쉬운 비유(학교 성적, 키 재기, 달리기 등)를 들어 매우 친절하고 흥미롭게 설명하십시오.
3. 답변과 함께 사용자가 클릭할 수 있는 후속 추천 질문 2~3개를 JSON 필드(suggested_questions)로 제안하십시오.
   (단, 추천 질문 목록에는 반드시 '쉽게 설명해줘' 관련 질문이 항상 최소 1개 포함되어야 합니다. 예: '중학생도 이해할 수 있게 쉽게 설명해줘')

반드시 아래 JSON 형식으로만 응답하십시오:
{{
  "reply": "마크다운 형식의 친절하고 명쾌한 답변 내용",
  "suggested_questions": [
    "중학생도 이해할 수 있게 쉽게 설명해줘",
    "이 결과에서 가장 의외였던 점은 뭐야?",
    "제외된 항목들은 왜 빠진 거야?"
  ]
}}
"""

    logger.info(f"[REQUEST] POST /chat (question='{user_message[:30]}...')")
    logger.info("[AI] chat 후속 질문 요청 시작")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=chat_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3
            )
        )
        logger.info("[AI] chat 후속 질문 응답 수신")
        parsed = json.loads(response.text.strip())

        reply = parsed.get("reply", response.text)
        suggested_q = parsed.get("suggested_questions", [
            "중학생도 이해할 수 있게 쉽게 설명해줘",
            "이 데이터에서 가장 주의해야 할 점은 뭐야?",
            "제외된 국가들은 왜 빠진 거야?"
        ])

        # '쉽게 설명해줘' 문구가 반드시 포함되도록 가드레일 보장
        if not any("쉽게" in q for q in suggested_q):
            suggested_q.insert(0, "중학생도 이해할 수 있게 쉽게 설명해줘")

        return jsonify({
            "status": "success",
            "reply": reply,
            "suggested_questions": suggested_q
        })
    except Exception as e:
        logger.error(f"[ERROR] Gemini chat 호출 실패: {str(e)}", exc_info=True)
        return jsonify({"error": f"답변 생성 중 오류가 발생했습니다: {str(e)}"}), 500

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    logger.info("Starting Flask server on http://127.0.0.1:5000 ...")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
