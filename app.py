import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" [cite: 1]
API_URL = "https://api.siliconflow.cn/v1/chat/completions" [cite: 1]
# 仅保留 Qwen 官方最新可用路径，确保 72B 波动时能安全降级到 7B
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct"] [cite: 1]

# --- 2. 页面设置与 CSS 注入 ---
st.set_page_config(page_title="AI 发票助手(QwenVL可编辑版)", layout="wide") [cite: 14]

st.markdown("""
    <style>
    div.stDownloadButton > button {
        background-color: #007bff !important; color: white !important; border: none !important;
        padding: 0.5rem 1.2rem !important; border-radius: 8px !important; width: auto !important;
    }
    div.stDownloadButton > button:hover { background-color: #0056b3 !important; }
    .total-container { display: flex; align-items: baseline; justify-content: flex-end; gap: 15px; margin-top: 20px; }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    .dashboard-box {
        padding: 15px; border-radius: 10px; background-color: #f8f9fa; border: 1px solid #e9ecef;
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True) [cite: 1, 2, 3, 4, 5, 6, 7, 8, 9]

# --- 3. 初始化持久化状态 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {} [cite: 14]
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set() [cite: 14]
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set() [cite: 14]

# 初始化 HTTP 长连接会话，提升处理稳定性
if 'http_session' not in st.session_state:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    st.session_state.http_session = session

# --- 4. 核心功能函数 ---

def call_api_once(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8') [cite: 10]
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"} [cite: 10]
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}" [cite: 10]

    last_error = ""
    for model in CANDIDATE_MODELS:
        if log_placeholder: log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp; 正在连接模型 `{model}`...") [cite: 10]
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}],
            "max_tokens": 512, "temperature": 0.1
        } [cite: 10]
        try:
            resp = st.session_state.http_session.post(API_URL, headers=headers, json=data, timeout=60) [cite: 11]
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content'] [cite: 11]
                clean = content.replace("```json", "").replace("```", "").strip() [cite: 11]
                s, e = clean.find('{'), clean.rfind('}') + 1 [cite: 11]
                return json.loads(clean[s:e]), None [cite: 12]
            else:
                last_error = f"HTTP {resp.status_code}: {resp.json().get('message', resp.text[:50])}"
        except Exception as e:
            last_error = str(e)
    return None, last_error

# 表格修改回调函数：确保改名和修改金额“一次生效”
def on_table_change():
    state = st.session_state["invoice_editor"]
    current_data = st.session_state.get('current_table_data', [])
    for idx, changes in state["edited_rows"].items():
        row_idx = int(idx)
        if row_idx < len(current_data):
            fid = current_data[row_idx]['file_id']
            if "文件名" in changes:
                st.session_state.renamed_files[fid] = changes["文件名"]
            if "金额" in changes and fid in st.session_state.invoice_cache:
                if st.session_state.invoice_cache[fid].get('data'):
                    st.session_state.invoice_cache[fid]['data']['Total'] = changes["金额"] [cite: 33]

# --- 5. 主程序 ---
st.title("AI 发票助手(QwenVL可编辑版)") [cite: 14]

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True) [cite: 14]

if uploaded_files:
    st.divider()
    
    # 实时看板占位
    dash_placeholder = st.empty()
    def render_live_stats():
        s_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'success') [cite: 15, 16]
        f_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'failed') [cite: 15, 16]
        dash_placeholder.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item"> 文件总数: {len(uploaded_files)}</div>
                <div class="stat-item stat-success"> 识别成功: {s_count}</div>
                <div class="stat-item stat-fail"> 识别失败: {f_count}</div>
                <div class="stat-item" style="color:#666"> 待处理: {len(uploaded_files) - s_count - f_count}</div>
            </div>
        """, unsafe_allow_html=True) [cite: 17, 18]

    render_live_stats() [cite: 18]

    # 队列计算
    queue = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.processed_session_ids and st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') != 'success'] [cite: 15]

    if queue:
        prog = st.progress(0) [cite: 19]
        status_txt = st.empty() [cite: 19]
        log_area = st.empty() [cite: 19]
        
        for i, file in enumerate(queue):
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid) [cite: 19]
            d_name = st.session_state.renamed_files.get(fid, file.name)
            status_txt.markdown(f"<div class='processing-highlight'> 正在处理 ({i+1}/{len(queue)}): {d_name}</div>", unsafe_allow_html=True) [cite: 19]
            
            try:
                file.seek(0) [cite: 20]
                f_bytes = file.read() [cite: 20]
                m_type = file.type [cite: 20]
                if m_type == "application/pdf":
                    log_area.caption(" PDF 转图片中...") [cite: 20]
                    images = convert_from_bytes(f_bytes) [cite: 20]
                    if images:
                        buf = io.BytesIO() [cite: 21]
                        images[0].save(buf, format="JPEG") [cite: 21]
                        f_bytes, m_type = buf.getvalue(), "image/jpeg" [cite: 21]
                
                res, err_msg = call_api_once(f_bytes, m_type, log_area)
                if res:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': res} [cite: 23]
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': err_msg} [cite: 23]
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': str(e)} [cite: 24]
            
            render_live_stats() [cite: 25]
            prog.progress((i + 1) / len(queue)) [cite: 25]
            time.sleep(0.8)
        
        st.rerun()

    # 数据表格准备
    table_data = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        d_name = st.session_state.renamed_files.get(fid, f.name)
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                res = cache['data'] [cite: 27]
                try: amt = float(str(res.get('Total', 0)).replace(',','').replace('元','')) [cite: 27]
                except: amt = 0.0 [cite: 27]
                table_data.append({"文件名": d_name, "日期": res.get('Date',''), "项目": res.get('Item',''), "金额": amt, "状态": " 成功", "file_id": fid}) [cite: 27]
            elif cache['status'] == 'failed':
                err = cache.get('error', '重试耗尽') [cite: 28]
                table_data.append({"文件名": d_name, "日期": "失败", "项目": f"❌ {err}", "金额": 0.0, "状态": " 失败", "file_id": fid}) [cite: 28]

    st.session_state.current_table_data = table_data
    if table_data:
        # 重试按钮区域
        failed_count = sum(1 for r in table_data if r['状态'].strip() == "失败") [cite: 28]
        if failed_count > 0:
            c1, c2 = st.columns([8, 2]) [cite: 29]
            with c1: st.warning(f" 有 {failed_count} 张文件识别失败，已开启报错显影，请检查报错原因。") [cite: 29]
            with c2: 
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True): [cite: 29]
                    for r in table_data:
                        if r['状态'].strip() == "失败":
                            st.session_state.processed_session_ids.discard(r['file_id']) [cite: 30]
                    st.rerun()

        # 数据编辑器
        df = pd.DataFrame(table_data)
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None, 
                "金额": st.column_config.NumberColumn(format="%.2f"), [cite: 31]
                "状态": st.column_config.TextColumn(disabled=True), [cite: 31]
                "文件名": st.column_config.TextColumn(disabled=False) [cite: 31]
            },
            use_container_width=True, 
            key="invoice_editor",
            on_change=on_table_change
        )
        
        # 底部合计与导出
        total = sum(r['金额'] for r in table_data if r['状态'].strip() == "成功") [cite: 33]
        c_l, c_r = st.columns([7, 3]) [cite: 34]
        with c_l:
            st.markdown(f"""<div class="total-container"><span class="total-label"> 总金额合计</span><span class="total-value"> {total:,.2f}</span></div>""", unsafe_allow_html=True) [cite: 34]
        with c_r:
            out = io.BytesIO() [cite: 34]
            exp_df = df.drop(columns=["file_id"]) [cite: 34]
            exp_df.loc[len(exp_df)] = ['合计', '', '', total, ''] [cite: 34]
            with pd.ExcelWriter(out, engine='openpyxl') as writer: exp_df.to_excel(writer, index=False) [cite: 35]
            st.download_button("导出 Excel", out.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True) [cite: 35]
else:
    st.info("👆 请上传发票文件。")
