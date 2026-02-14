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
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
if 'http_session' not in st.session_state: st.session_state.http_session = requests.Session()

# --- 4. 功能函数 ---
def call_api_once(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    session = st.session_state.http_session
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    last_error = ""
    for i, model in enumerate(CANDIDATE_MODELS):
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
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

# --- 5. 主程序 ---
st.title("AI 发票助手(QwenVL可编辑版)")

uploaded_files = st.file_uploader("上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    # 准备队列
    queue = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        status = st.session_state.invoice_cache.get(fid, {}).get('status')
        if status != 'success' and fid not in st.session_state.processed_session_ids:
            queue.append(f)

    # 【修复重点：定义实时看板渲染函数】
    dash_placeholder = st.empty()
    def render_live_stats():
        s_count = 0
        f_count = 0
        for f in uploaded_files:
            fid = f"{f.name}_{f.size}"
            stat = st.session_state.invoice_cache.get(fid, {}).get('status')
            if stat == 'success': s_count += 1
            elif stat == 'failed': f_count += 1
        
        dash_placeholder.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item">文件总数: {len(uploaded_files)}</div>
                <div class="stat-item stat-success">识别成功: {s_count}</div>
                <div class="stat-item stat-fail">识别失败: {f_count}</div>
                <div class="stat-item" style="color:#666">待处理: {len(uploaded_files) - s_count - f_count}</div>
            </div>
        """, unsafe_allow_html=True)

    # 初始渲染
    render_live_stats()

    if queue:
        prog = st.progress(0)
        status_txt = st.empty()
        
        for i, file in enumerate(queue):
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid)
            status_txt.markdown(f"**正在处理 ({i+1}/{len(queue)}):** {file.name}")
            
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
                
                res, err_msg = call_api_once(f_bytes, m_type, None)
                if res:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': res}
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': err_msg}
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': str(e)}
            
            # 【修复重点：每处理完一个，立即调用渲染函数更新看板】
            render_live_stats()
            prog.progress((i + 1) / len(queue))
            time.sleep(0.5) 
            
        st.rerun()

    # 表格显示逻辑 (保持原样...)
    # ... (省略重复的表格渲染代码以节省空间)
