import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
# 仅保留 Qwen 系列，移除失效的 TeleMM 防止误导报错
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct"]

# --- 2. 页面设置 ---
st.set_page_config(page_title="AI 发票助手(QwenVL可编辑版)", layout="wide")

st.markdown("""
    <style>
    div.stDownloadButton > button { background-color: #007bff !important; color: white !important; border: none !important; border-radius: 8px !important; }
    .dashboard-box { padding: 15px; border-radius: 10px; background-color: #f8f9fa; border: 1px solid #e9ecef; margin-bottom: 20px; display: flex; gap: 20px; align-items: center; }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    .total-container { display: flex; align-items: baseline; justify-content: flex-end; gap: 15px; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    </style>
""", unsafe_allow_html=True)

# --- 3. Session 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
if 'http_session' not in st.session_state: st.session_state.http_session = requests.Session() # 全局长连接

# --- 4. 核心功能函数 ---

def call_api_once(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    # 使用保持的长连接会话
    session = st.session_state.http_session
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    last_error = ""
    for i, model in enumerate(CANDIDATE_MODELS):
        if i > 0:
            if log_placeholder: log_placeholder.warning(f"⚠️ 正在切换备选模型: {model}...")
            time.sleep(1.5) # 切换模型间隔

        data = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            # 增加超时到 60s 以应对大模型处理波动
            resp = session.post(API_URL, headers=headers, json=data, timeout=60)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e]), None
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:50]}"
        except Exception as e:
            last_error = str(e)
    return None, last_error

def analyze_with_retry(image_bytes, mime_type, log_container):
    MAX_RETRIES = 2 # 内部重试 2 次
    final_err = ""
    for attempt in range(1, MAX_RETRIES + 1):
        result, err = call_api_once(image_bytes, mime_type, log_container)
        if result: return result, None
        final_err = err
        time.sleep(attempt * 2) 
    return None, final_err

def on_table_change():
    state = st.session_state["invoice_editor"]
    current_data = st.session_state.get('current_table_data', [])
    for idx, changes in state["edited_rows"].items():
        row_idx = int(idx)
        if row_idx < len(current_data):
            fid = current_data[row_idx]['file_id']
            if "文件名" in changes: st.session_state.renamed_files[fid] = changes["文件名"]
            if "金额" in changes and fid in st.session_state.invoice_cache:
                if st.session_state.invoice_cache[fid].get('data'):
                    st.session_state.invoice_cache[fid]['data']['Total'] = changes["金额"]

# --- 5. 主程序 ---
st.title(" AI 发票助手(QwenVL可编辑版)")

uploaded_files = st.file_uploader("上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    # 计算待处理队列
    queue = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        status = st.session_state.invoice_cache.get(fid, {}).get('status')
        if status != 'success' and fid not in st.session_state.processed_session_ids:
            queue.append(f)

    # 看板渲染
    success_c = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'success')
    fail_c = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'failed')
    st.markdown(f'<div class="dashboard-box"><div class="stat-item">总数: {len(uploaded_files)}</div><div class="stat-item stat-success">成功: {success_c}</div><div class="stat-item stat-fail">失败: {fail_c}</div></div>', unsafe_allow_html=True)

    if queue:
        prog = st.progress(0)
        log_area = st.empty()
        for i, file in enumerate(queue):
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid)
            d_name = st.session_state.renamed_files.get(fid, file.name)
            log_area.markdown(f"**正在处理 ({i+1}/{len(queue)}):** {d_name}")
            try:
                file.seek(0)
                f_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    images = convert_from_bytes(f_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                res, err_msg = analyze_with_retry(f_bytes, m_type, log_area)
                if res:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': res}
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': err_msg}
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': str(e)}
            prog.progress((i + 1) / len(queue))
            time.sleep(1.0) # 强制间隔，保护连接
        st.rerun()

    # 表格准备
    table_data = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        name = st.session_state.renamed_files.get(fid, f.name)
        cache = st.session_state.invoice_cache.get(fid)
        if cache and cache['status'] == 'success':
            d = cache['data']
            table_data.append({"文件名": name, "日期": d.get('Date',''), "项目": d.get('Item',''), "金额": d.get('Total',0), "状态": "成功", "file_id": fid})
        elif cache and cache['status'] == 'failed':
            table_data.append({"文件名": name, "日期": "失败", "项目": f"❌ {cache.get('error','')}", "金额": 0.0, "状态": "失败", "file_id": fid})
    
    st.session_state.current_table_data = table_data
    if table_data:
        # 重试按钮
        if any(r['状态'] == '失败' for r in table_data):
            if st.button("🔄 重试失败任务", type="primary"):
                for r in table_data:
                    if r['状态'] == '失败' and r['file_id'] in st.session_state.processed_session_ids:
                        st.session_state.processed_session_ids.remove(r['file_id'])
                st.rerun()
        
        # 可编辑表格
        edited = st.data_editor(pd.DataFrame(table_data), column_config={"file_id": None, "金额": st.column_config.NumberColumn(format="%.2f")}, use_container_width=True, key="invoice_editor", on_change=on_table_change)
        
        # 统计合计
        total_amt = sum(r['金额'] for r in table_data if r['状态'] == '成功')
        st.markdown(f'<div class="total-container"><span class="total-value">合计: {total_amt:,.2f}</span></div>', unsafe_allow_html=True)
