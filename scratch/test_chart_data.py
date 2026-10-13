import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app import app

client = app.test_client()

def test_chart_data_structure():
    print("=== [1] Upload CSV ===")
    csv_path = r"data\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465\API_IT.NET.USER.ZS_DS2_en_csv_v2_468465.csv"
    with open(csv_path, "rb") as f:
        res = client.post("/inspect", data={"file": (f, "test.csv")})
    assert res.status_code == 200

    print("=== [2] Test NL Query 1 (compare_one_vs_all) ===")
    res_q1 = client.post("/query", json={"query": "한국의 인터넷 사용률 순위는?"})
    assert res_q1.status_code == 200
    d1 = res_q1.get_json()
    
    # calc_result
    calc_res1 = d1.get("result", {})
    inner_res1 = calc_res1.get("result", {})
    chart_data1 = inner_res1.get("chart_data") or calc_res1.get("chart_data")
    
    print("Tool:", d1.get("tool"))
    print("Chart data exists?", chart_data1 is not None)
    print("Chart type:", chart_data1.get("type"))
    print("Chart labels:", chart_data1.get("labels"))
    print("Chart values:", chart_data1.get("values"))
    assert chart_data1 is not None, "chart_data is missing!"
    assert len(chart_data1.get("labels", [])) > 0, "chart labels are empty!"
    assert len(chart_data1.get("values", [])) > 0, "chart values are empty!"

    print("\n=== [3] Test NL Query 2 (top_bottom_n) ===")
    res_q2 = client.post("/query", json={"query": "2024년 상위 5개국 순위"})
    assert res_q2.status_code == 200
    d2 = res_q2.get_json()
    
    calc_res2 = d2.get("result", {})
    inner_res2 = calc_res2.get("result", {})
    chart_data2 = inner_res2.get("chart_data") or calc_res2.get("chart_data")
    
    print("Tool:", d2.get("tool"))
    print("Chart data exists?", chart_data2 is not None)
    print("Chart labels:", chart_data2.get("labels"))
    print("Chart values:", chart_data2.get("values"))
    assert chart_data2 is not None, "chart_data is missing!"
    assert len(chart_data2.get("labels", [])) == 5, f"expected 5 labels, got {len(chart_data2.get('labels', []))}"
    
    print("\n=== Chart Data Structure Verified Successfully! ===")

if __name__ == "__main__":
    test_chart_data_structure()
