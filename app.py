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
# 仅保留有效模型，避免 TeleMM 导致误报
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
    .total-container { display: flex; align-items: baseline; justify-content: flex-end; gap: 15px; margin-top: 20px; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
if 'http_session' not in st.session_state: st.session_state.http_session = requests.Session()

# --- 4. 核心功能函数 ---
def call_api_once(image_bytes, mime_type):
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

# 回调函数：表格改名/改金额即时生效
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
                    st.session_state.invoice_cache[fid]['data']['Total'] = changes["金额"]

# --- 5. 主程序 ---
st.title("AI 发票助手(QwenVL可编辑版)")

uploaded_files = st.file_uploader("上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    # 统计与队列
    queue = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        status = st.session_state.invoice_cache.get(fid, {}).get('status')
        if status != 'success' and fid not in st.session_state.processed_session_ids:
            queue.append(f)

    # 实时看板占位
    dash_placeholder = st.empty()
    def render_live_stats():
        s_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'success')
        f_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'failed')
        dash_placeholder.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item">总数: {len(uploaded_files)}</div>
                <div class="stat-item stat-success">识别成功: {s_count}</div>
                <div class="stat-item stat-fail">识别失败: {f_count}</div>
                <div class="stat-item" style="color:#666">待处理: {len(uploaded_files) - s_count - f_count}</div>
            </div>
        """, unsafe_allow_html=True)

    render_live_stats()

    # 处理循环
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
                
                res, err_msg = call_api_once(f_bytes, m_type)
                if res:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': res}
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': err_msg}
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': str(e)}
            
            render_live_stats()
            prog.progress((i + 1) / len(queue))
            time.sleep(1.0) # 降速保护连接
        
        status_txt.empty()
        prog.empty()
        st.rerun()

    # === 核心闭环：表格数据渲染与重试按钮 ===
    table_data = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        name = st.session_state.renamed_files.get(fid, f.name)
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                d = cache['data']
                table_data.append({"文件名": name, "日期": d.get('Date',''), "项目": d.get('Item',''), "金额": d.get('Total',0), "状态": "成功", "file_id": fid})
            elif cache['status'] == 'failed':
                # 报错显影功能
                err = cache.get('error', '未知错误')
                table_data.append({"文件名": name, "日期": "失败", "项目": f"❌ {err}", "金额": 0.0, "状态": "失败", "file_id": fid})

    st.session_state.current_table_data = table_data
    if table_data:
        st.divider()
        # 重试按钮：处理失败的任务
        failed_count = sum(1 for r in table_data if r['状态'] == '失败')
        if failed_count > 0:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning(f"当前有 {failed_count} 个任务识别失败。")
            with c2:
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True):
                    for r in table_data:
                        if r['状态'] == '失败' and r['file_id'] in st.session_state.processed_session_ids:
                            st.session_state.processed_session_ids.remove(r['file_id'])
                    st.rerun()

        # 表格显示
        df = pd.DataFrame(table_data)
        edited = st.data_editor(
            df,
            column_config={
                "file_id": None,
                "金额": st.column_config.NumberColumn(format="%.2f"),
                "状态": st.column_config.TextColumn(disabled=True),
                "文件名": st.column_config.TextColumn(disabled=False)
            },
            use_container_width=True,
            key="invoice_editor",
            on_change=on_table_change
        )
        
        # 合计金额与导出
        total_amt = sum(r['金额'] for r in table_data if r['状态'] == '成功')
        bc1, bc2 = st.columns([7, 3])
        with bc1:
            st.markdown(f'<div class="total-container"><span class="total-value">合计: {total_amt:,.2f}</span></div>', unsafe_allow_html=True)
        with bc2:
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer: df.drop(columns=['file_id']).to_excel(writer, index=False)
            st.download_button("导出 Excel", out.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
else:
    st.info("👆 请上传发票文件开始处理。")
