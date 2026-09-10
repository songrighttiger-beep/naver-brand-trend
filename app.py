import requests
import time
import io
import math
import os
import sys
import webbrowser
import threading
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)
from brand_korean_names import generate_keywords, BRAND_KOREAN_NAMES

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"), static_folder=os.path.join(BASE_DIR, "static"))
CORS(app)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

API_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
DAILY_QUOTA = 1000

progress_store = {}
progress_lock = threading.Lock()

api_quota = {"date": time.strftime("%Y-%m-%d"), "count": 0, "history": []}
quota_lock = threading.Lock()


def increment_api_count():
    with quota_lock:
        today = time.strftime("%Y-%m-%d")
        if api_quota["date"] != today:
            api_quota["history"].append({"date": api_quota["date"], "count": api_quota["count"]})
            if len(api_quota["history"]) > 30:
                api_quota["history"].pop(0)
            api_quota["date"] = today
            api_quota["count"] = 0
        api_quota["count"] += 1


def call_naver_api(client_id, client_secret, body):
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
        "Content-Type": "application/json"
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(API_URL, headers=headers, json=body, timeout=30)
            increment_api_count()
            if resp.status_code == 200:
                return resp.json(), None
            elif resp.status_code == 429:
                return None, "API调用额度已用尽 (429)。"
            elif resp.status_code == 401:
                return None, "认证失败 (401)。请确认Client ID/Secret。"
            elif resp.status_code == 400:
                try:
                    err = resp.json()
                    return None, f"请求错误 (400): {err.get('errMsg', resp.text)}"
                except:
                    return None, f"请求错误 (400): {resp.text}"
            else:
                return None, f"API错误 ({resp.status_code}): {resp.text}"
        except requests.exceptions.SSLError:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None, f"SSL连接错误 (尝试{attempt+1}次)。"
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None, "网络连接错误。"
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                continue
            return None, "请求超时。"
        except Exception as e:
            return None, f"未知错误: {str(e)}"
    return None, "API调用失败。"


def process_brands(client_id, client_secret, brands, anchor, start_date, end_date,
                   time_unit, task_id):
    with progress_lock:
        progress_store[task_id] = {
            "status": "running", "current": 0, "total": 0,
            "message": "初始化中...", "results": {}, "errors": []
        }

    try:
        non_anchor = [b for b in brands if b != anchor]
        batch_size = 4
        batches = [non_anchor[i:i+batch_size] for i in range(0, len(non_anchor), batch_size)]
        total_calls = len(batches)

        with progress_lock:
            progress_store[task_id]["total"] = total_calls

        all_raw = {}
        reference_anchor_avg = None

        for i, batch in enumerate(batches):
            with progress_lock:
                progress_store[task_id]["current"] = i + 1
                progress_store[task_id]["message"] = f"第{i+1}/{total_calls}次调用... 品牌: {', '.join(batch[:2])}..."

            anchor_keywords = generate_keywords(anchor)
            groups = [{"groupName": anchor, "keywords": anchor_keywords}]
            for brand in batch:
                brand_keywords = generate_keywords(brand)
                groups.append({"groupName": brand, "keywords": brand_keywords})

            body = {
                "startDate": start_date,
                "endDate": end_date,
                "timeUnit": time_unit,
                "keywordGroups": groups
            }

            result, error = call_naver_api(client_id, client_secret, body)
            if error:
                with progress_lock:
                    progress_store[task_id]["errors"].append(error)
                    if "429" in error or "401" in error:
                        progress_store[task_id]["status"] = "error"
                        progress_store[task_id]["message"] = error
                        return
                continue

            if result:
                this_anchor_ratios = []
                for r in result.get("results", []):
                    brand = r["title"]
                    if brand not in all_raw:
                        all_raw[brand] = {}
                    for d in r["data"]:
                        period = d["period"]
                        ratio = d["ratio"]
                        all_raw[brand][period] = ratio
                        if brand == anchor:
                            this_anchor_ratios.append(ratio)

                this_anchor_avg = sum(this_anchor_ratios) / len(this_anchor_ratios) if this_anchor_ratios else 1
                if reference_anchor_avg is None:
                    reference_anchor_avg = this_anchor_avg

                scale = reference_anchor_avg / this_anchor_avg if this_anchor_avg > 0 else 1

                for r in result.get("results", []):
                    brand = r["title"]
                    for d in r["data"]:
                        period = d["period"]
                        all_raw[brand][period] = round(d["ratio"] * scale, 2)

            time.sleep(0.1)

        global_max = 0
        for brand, periods in all_raw.items():
            for period, ratio in periods.items():
                if ratio > global_max:
                    global_max = ratio

        scale_to_100 = 100 / global_max if global_max > 0 else 1

        all_results = {}
        for brand, periods in all_raw.items():
            all_results[brand] = []
            for period in sorted(periods.keys()):
                unified = round(periods[period] * scale_to_100, 2)
                all_results[brand].append({"period": period, "ratio": unified})

        with progress_lock:
            progress_store[task_id]["status"] = "completed"
            progress_store[task_id]["message"] = f"完成! 已处理{len(all_results)}个品牌。API调用: {len(batches)}次"
            progress_store[task_id]["results"] = all_results
            progress_store[task_id]["api_calls"] = len(batches)

    except Exception as e:
        with progress_lock:
            progress_store[task_id]["status"] = "error"
            progress_store[task_id]["message"] = f"处理过程中发生错误: {str(e)}"


def generate_excel(results, brands, anchor, start_date, end_date, time_unit):
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine="openpyxl")

    sample_brand = next((b for b in brands if b in results), None)
    periods = []
    if sample_brand and results.get(sample_brand):
        periods = [d["period"] for d in results[sample_brand]]

    summary_data = []
    for brand in brands:
        korean_name = BRAND_KOREAN_NAMES.get(brand, "")
        if brand in results and results[brand]:
            ratios = [d["ratio"] for d in results[brand]]
            avg = round(sum(ratios) / len(ratios), 2) if ratios else 0
            max_val = max(ratios) if ratios else 0
            min_val = min(ratios) if ratios else 0
            summary_data.append({"品牌": brand, "韩文名": korean_name, "平均": avg, "最大": max_val, "最小": min_val, "数据数": len(ratios)})
        else:
            summary_data.append({"品牌": brand, "韩文名": korean_name, "平均": 0, "最大": 0, "最小": 0, "数据数": 0})

    df_summary = pd.DataFrame(summary_data)
    df_summary = df_summary.sort_values("平均", ascending=False).reset_index(drop=True)
    df_summary.insert(0, "排名", range(1, len(df_summary) + 1))
    df_summary.to_excel(writer, sheet_name="汇总", index=False)

    if periods:
        trend_data = {"品牌": brands}
        for period in periods:
            col_data = []
            for brand in brands:
                if brand in results and results[brand]:
                    period_data = {d["period"]: d["ratio"] for d in results[brand]}
                    col_data.append(period_data.get(period, 0))
                else:
                    col_data.append(0)
            trend_data[period] = col_data

        df_trend = pd.DataFrame(trend_data)
        df_trend.to_excel(writer, sheet_name="趋势", index=False)

        pivot_rows = []
        for brand in brands:
            korean_name = BRAND_KOREAN_NAMES.get(brand, "")
            if brand in results and results[brand]:
                for d in results[brand]:
                    pivot_rows.append({
                        "品牌": brand,
                        "韩文名": korean_name,
                        "期间": d["period"],
                        "搜索比例": d["ratio"]
                    })

        if pivot_rows:
            df_pivot = pd.DataFrame(pivot_rows)
            df_pivot.to_excel(writer, sheet_name="透视数据", index=False)

    writer.close()
    output.seek(0)
    return output


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/quota")
def get_quota():
    with quota_lock:
        used = api_quota["count"]
        remaining = DAILY_QUOTA - used
        pct = round(used / DAILY_QUOTA * 100, 1)
        if pct < 70:
            level = "green"
        elif pct < 90:
            level = "yellow"
        else:
            level = "red"
        return jsonify({
            "used": used,
            "total": DAILY_QUOTA,
            "remaining": remaining,
            "percent": pct,
            "level": level,
            "date": api_quota["date"],
            "history": api_quota["history"][-7:]
        })


@app.route("/api/preview-keywords", methods=["POST"])
def preview_keywords():
    data = request.json
    brands_input = data.get("brands", "")
    brands = [b.strip() for b in brands_input.split("\n") if b.strip()]
    preview = {}
    for brand in brands[:20]:
        preview[brand] = generate_keywords(brand)
    return jsonify({"preview": preview, "total": len(brands)})


@app.route("/api/search", methods=["POST"])
def search():
    data = request.json
    client_id = data.get("clientId", "").strip()
    client_secret = data.get("clientSecret", "").strip()
    brands_input = data.get("brands", "")
    anchor = data.get("anchor", "").strip()
    start_date = data.get("startDate", "")
    end_date = data.get("endDate", "")
    time_unit = data.get("timeUnit", "month")

    if not client_id or not client_secret:
        return jsonify({"error": "请输入API密钥。"}), 400
    if not brands_input:
        return jsonify({"error": "请输入品牌。"}), 400
    if not anchor:
        return jsonify({"error": "请输入锚点品牌。"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "请设置查询期间。"}), 400

    brands = [b.strip() for b in brands_input.split("\n") if b.strip()]
    if anchor not in brands:
        brands.insert(0, anchor)
    if len(brands) > 500:
        return jsonify({"error": "品牌最多500个。"}), 400

    task_id = f"task_{int(time.time() * 1000)}"
    thread = threading.Thread(
        target=process_brands,
        args=(client_id, client_secret, brands, anchor, start_date, end_date, time_unit, task_id)
    )
    thread.daemon = True
    thread.start()
    return jsonify({"taskId": task_id, "brandCount": len(brands)})


@app.route("/api/progress/<task_id>")
def get_progress(task_id):
    with progress_lock:
        if task_id not in progress_store:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(progress_store[task_id])


@app.route("/api/export", methods=["POST"])
def export_excel():
    data = request.json
    results = data.get("results", {})
    brands = data.get("brands", [])
    anchor = data.get("anchor", "")
    start_date = data.get("startDate", "")
    end_date = data.get("endDate", "")
    time_unit = data.get("timeUnit", "month")

    output = generate_excel(results, brands, anchor, start_date, end_date, time_unit)
    return send_file(
        output, as_attachment=True,
        download_name=f"naver_trend_{start_date}_{end_date}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/api/upload-brands", methods=["POST"])
def upload_brands():
    if "file" not in request.files:
        return jsonify({"error": "没有文件。"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "没有文件名。"}), 400
    try:
        if file.filename.endswith(".xlsx"):
            df = pd.read_excel(file)
            brands = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
        elif file.filename.endswith(".csv"):
            df = pd.read_csv(file)
            brands = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
        elif file.filename.endswith(".txt"):
            content = file.read().decode("utf-8")
            brands = [b.strip() for b in content.split("\n") if b.strip()]
        else:
            return jsonify({"error": "不支持的文件格式。"}), 400
        if not brands:
            return jsonify({"error": "未找到品牌。"}), 400
        return jsonify({"brands": brands, "count": len(brands)})
    except Exception as e:
        return jsonify({"error": f"文件读取错误: {str(e)}"}), 500


def open_browser():
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    if getattr(sys, 'frozen', False):
        threading.Timer(1.5, open_browser).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
