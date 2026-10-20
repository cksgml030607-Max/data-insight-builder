import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app import app

client = app.test_client()

def test_top30():
    print("=== [1] CSV 업로드 ===")
    csv_path = r"data\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv"
    with open(csv_path, "rb") as f:
        res = client.post("/inspect", data={"file": (f, "test.csv")})
    assert res.status_code == 200

    print("=== [2] 자연어 질문: 인터넷 사용률 top 30 국가 ===")
    res_q = client.post("/query", json={"query": "인터넷 사용률 top 30 국가 알려줘"})
    assert res_q.status_code == 200
    data = res_q.get_json()

    print("도구:", data.get("tool"))
    print("매개변수:", data.get("params"))
    assert data.get("tool") == "top_bottom_n"
    assert data.get("params", {}).get("n") == 30

    calc_res = data.get("result", {})
    inner = calc_res.get("result", {})
    chart_data = inner.get("chart_data", {})
    labels = chart_data.get("labels", [])
    values = chart_data.get("values", [])
    
    print(f"차트 레이블 개수: {len(labels)}")
    print(f"차트 수치 개수: {len(values)}")
    assert len(labels) == 30, f"Expected 30 labels, got {len(labels)}"
    assert len(values) == 30, f"Expected 30 values, got {len(values)}"

    top_records = inner.get("top_records", [])
    print(f"상세 레코드 개수: {len(top_records)}")
    assert len(top_records) == 30
    print(f"1위: {top_records[0]['label']} ({top_records[0]['value']}%)")
    print(f"30위: {top_records[29]['label']} ({top_records[29]['value']}%)")

    print("\n=== TOP 30 Query Test Passed Successfully! ===")

if __name__ == "__main__":
    test_top30()
