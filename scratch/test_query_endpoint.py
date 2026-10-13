import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# app 임포트
from app import app, CURRENT_DATASET

client = app.test_client()

def test_query_flow():
    print("=== [1] CSV 업로드 & inspect ===")
    csv_path = r"data\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv"
    with open(csv_path, "rb") as f:
        res = client.post("/inspect", data={"file": (f, "test.csv")})
    assert res.status_code == 200, f"Inspect failed: {res.data}"
    inspect_data = res.get_json()
    print("Inspect OK. Shape:", inspect_data["rows"], "rows,", inspect_data["columns"], "cols")
    print("Recommended year:", inspect_data["recommended_year"])

    print("\n=== [2] 자연어 질문 1: 한국의 인터넷 사용률 순위 ===")
    q1 = "한국의 인터넷 사용률 순위와 위치는 어떻게 돼?"
    res_q1 = client.post("/query", json={"query": q1})
    print("Status:", res_q1.status_code)
    data1 = res_q1.get_json()
    assert res_q1.status_code == 200, f"Query 1 failed: {data1}"
    print("Tool selected:", data1.get("tool"), f"({data1.get('tool_name_ko')})")
    print("Params:", data1.get("params"))
    print("Answer:\n", data1.get("answer"))
    print("Result rows used:", data1.get("result", {}).get("rows_used"))
    print("Chart data labels count:", len(data1.get("result", {}).get("chart_data", {}).get("labels", [])))

    print("\n=== [3] 자연어 질문 2: 2024년 1위 국가와 TOP 5 ===")
    q2 = "2024년 1위 국가는 어디고 상위 5개국 알려줘"
    res_q2 = client.post("/query", json={"query": q2})
    print("Status:", res_q2.status_code)
    data2 = res_q2.get_json()
    assert res_q2.status_code == 200, f"Query 2 failed: {data2}"
    print("Tool selected:", data2.get("tool"), f"({data2.get('tool_name_ko')})")
    print("Answer:\n", data2.get("answer"))

    print("\n=== [4] latest_run 상태 확인 및 explain/chat 연계 확인 ===")
    assert "latest_run" in CURRENT_DATASET, "latest_run not saved in CURRENT_DATASET"
    print("CURRENT_DATASET latest_run tool:", CURRENT_DATASET["latest_run"]["tool"])

    print("\n=== All Tests Passed Successfully! ===")

if __name__ == "__main__":
    test_query_flow()
