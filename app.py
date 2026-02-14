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
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
# 当前最新可用模型列表
CANDIDATE_MODELS = [
    "Qwen/Qwen2.5-VL-72B-Instruct", 
    "deepseek-ai/DeepSeek-OCR",
    "zai-org/GLM-4.5V",
    "Pro/Qwen/Qwen2.5-VL-7B-Instruct"
]

# --- 2. 页面设置 ---
st.set_page_config(page_title="AI 发票助手(QwenVL可编辑版)", layout="wide")

st.markdown("""
    <style>
    /* 1. 蓝色按钮：取消固定宽度，根据文案自动调整 */
    div.stDownloadButton > button {
        background-color: #007bff !important; 
        color: white !important; 
        border: none !important; 
        border-radius: 8px !important;
        width: auto !important; /* 宽度自适应 */
        padding: 0.5rem 2rem !important; /* 增加一点左右内边距 */
        min-width: 120px !important;
    }
    div.stDownloadButton > button:hover { background-color: #0056b3 !important; }
    
    /* 2. 顶部统计看板样式 */
    .dashboard-box {
        padding: 15px; border-radius: 10px; background-color: #f8f9fa; border: 1px solid #e9ecef;
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    .stat-time { color: #007bff; }
    
    /* 3. 底部合计栏布局：确保金额和按钮紧挨并水平居中 */
    .footer-container {
        display: flex;
        justify-content: center; /* 水平居中 */
        align-items: center;     /* 垂直居中 */
        gap: 25px;               /* 金额与按钮的间距 */
        width: 100%;
        margin-top: 30px;
        padding: 20px 0;
    }
    .total-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #212529;
        margin: 0;
    }
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
if 'overall_duration' not in st.session_state: st.session_state.overall_duration = 0.0

if 'http_session' not in st.session_state:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=15, max_retries=retries)
    session.mount('https://', adapter)
    st.session_state.http_session = session

# --- 4. 核心功能函数 ---
def call_api_once(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    last_error = ""
    for model in CANDIDATE_MODELS:
        if log_placeholder: log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp; 正在尝试模型 `{model}`...")
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            resp = st.session_state.http_session.post(API_URL, headers=headers, json=data, timeout=60)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e]), None
            else:
                last_error = f"HTTP {resp.status_code}: {resp.json().get('message', '未知错误')}"
        except Exception as e:
            last_error = str(e)
        time.sleep(1.0)
    return None, last_error

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

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    dash_placeholder = st.empty()
    def render_live_stats(live_duration=None):
        s_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'success')
        f_count = sum(1 for f in uploaded_files if st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') == 'failed')
        final_time = live_duration if live_duration is not None else st.session_state.overall_duration
        
        dash_placeholder.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item">文件总数: {len(uploaded_files)}</div>
                <div class="stat-item stat-success">识别成功: {s_count}</div>
                <div class="stat-item stat-fail">识别失败: {f_count}</div>
                <div class="stat-item" style="color:#666">待处理: {len(uploaded_files)-s_count-f_count}</div>
                <div class="stat-item stat-time">整体耗时: {final_time:.1f}s</div>
            </div>
        """, unsafe_allow_html=True)

    render_live_stats()

    queue = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.processed_session_ids and st.session_state.invoice_cache.get(f"{f.name}_{f.size}", {}).get('status') != 'success']
    
    if queue:
        prog = st.progress(0)
        status_txt = st.empty()
        log_area = st.empty()
        task_start_time = time.time()
        
        for i, file in enumerate(queue):
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid)
            d_name = st.session_state.renamed_files.get(fid, file.name)
            status_txt.markdown(f"<div class='processing-highlight'>正在处理 ({i+1}/{len(queue)}): {d_name}</div>", unsafe_allow_html=True)
            
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
                
                res, err_msg = call_api_once(f_bytes, m_type, log_area)
                if res:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': res}
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': err_msg}
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed', 'error': str(e)}
            
            current_elapsed = time.time() - task_start_time
            render_live_stats(current_elapsed)
            prog.progress((i + 1) / len(queue))
            time.sleep(1.2)
        
        st.session_state.overall_duration = time.time() - task_start_time
        st.rerun()

    # 数据准备
    table_data = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        name = st.session_state.renamed_files.get(fid, f.name)
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                d = cache['data']
                try: amt = float(str(d.get('Total', 0)).replace(',','').replace('元',''))
                except: amt = 0.0
                table_data.append({"文件名": name, "日期": d.get('Date',''), "项目": d.get('Item',''), "金额": amt, "状态": "成功", "file_id": fid})
            elif cache['status'] == 'failed':
                err_info = cache.get('error', '识别超时')
                table_data.append({"文件名": name, "日期": "失败", "项目": f"❌ {err_info}", "金额": 0.0, "状态": "失败", "file_id": fid})

    st.session_state.current_table_data = table_data
    
    if table_data:
        st.divider()
        failed_count = sum(1 for r in table_data if r['状态'] == '失败')
        if failed_count > 0:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning(f"当前有 {failed_count} 个发票识别失败。")
            with c2:
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True):
                    for r in table_data:
                        if r['状态'] == '失败':
                            st.session_state.processed_session_ids.discard(r['file_id'])
                    st.rerun()

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
        
        # === 6. 底部合计与按钮优化区 ===
        total_amt = sum(r['金额'] for r in table_data if r['状态'] == '成功')
        
        # 使用 3 列布局：左边留白，中间对齐，右边留白，从而实现整体居中
        # 4:4:4 或 3:6:3 的比例可以让中间区域足够宽
        empty_l, center_content, empty_r = st.columns([3, 6, 3])
        
        with center_content:
            # 内部再次分割，让金额和按钮紧靠在一起并居中
            # 这里的比例 0.6:0.4 确保金额在左，按钮在右，且由于外部 column 已居中，这里也会居中
            sub_c1, sub_c2 = st.columns([0.65, 0.35])
            with sub_c1:
                st.markdown(f'<p class="total-value" style="text-align: right;">合计: {total_amt:,.2f}</p>', unsafe_allow_html=True)
            with sub_c2:
                # 导出 Excel 准备
                out = io.BytesIO()
                exp_df = df.drop(columns=['file_id'])
                exp_df.loc[len(exp_df)] = ['合计', '', '', total_amt, '']
                with pd.ExcelWriter(out, engine='openpyxl') as writer: exp_df.to_excel(writer, index=False)
                
                # 注意：此处没有设置 use_container_width=True，按钮将保持 CSS 定义的自适应宽度
                st.download_button(
                    label="导出 Excel", 
                    data=out.getvalue(), 
                    file_name="发票汇总.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
else:
    st.info("👆 请上传发票文件。")
