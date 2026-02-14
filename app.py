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
CANDIDATE_MODELS = [
    "Qwen/Qwen2.5-VL-72B-Instruct", 
    "deepseek-ai/DeepSeek-OCR",
    "zai-org/GLM-4.5V",
    "Pro/Qwen/Qwen2.5-VL-7B-Instruct"
]

# --- 2. 页面设置与 CSS 样式 ---
st.set_page_config(page_title="AI 发票助手(QwenVL可编辑版)", layout="wide")

st.markdown("""
    <style>
    /* 全局输入框样式 */
    .stTextInput > div > div > input {
        font-weight: bold;
        color: #007bff;
    }

    /* 顶部统计看板 */
    .dashboard-box {
        padding: 15px; border-radius: 10px; background-color: #f8f9fa; border: 1px solid #e9ecef;
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    .stat-time { color: #007bff; }
    
    /* 底部合计金额样式 */
    .total-display {
        font-size: 2.8rem;
        font-weight: 800;
        color: #1a1d21;
        display: flex;
        align-items: baseline;
        justify-content: flex-end; 
        line-height: 1.0;          
    }
    .total-label {
        font-size: 1.5rem;
        font-weight: 600;
        margin-right: 15px;
        color: #495057;
    }
    
    /* 蓝色按钮样式 */
    div.stDownloadButton > button {
        background-color: #007bff !important; 
        color: white !important; 
        border: none !important; 
        border-radius: 6px !important;
        width: auto !important;
        padding: 0.4rem 1.5rem !important;
        font-size: 0.95rem !important;
        transform: translateY(15px); 
        transition: all 0.3s ease;
    }
    div.stDownloadButton > button:hover { background-color: #0056b3 !important; transform: translateY(14px); }
    
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} 
# 新增：事项内容的缓存
if 'descriptions' not in st.session_state: st.session_state.descriptions = {} 
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
            # 1. 监听文件名修改
            if "文件名" in changes:
                st.session_state.renamed_files[fid] = changes["文件名"]
            # 2. 监听事项修改 (新功能)
            if "事项" in changes:
                st.session_state.descriptions[fid] = changes["事项"]
            # 3. 监听金额修改
            if "金额" in changes and fid in st.session_state.invoice_cache:
                if st.session_state.invoice_cache[fid].get('status') == 'success':
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
                elif m_type == 'image/jpg': m_type = 'image/jpeg'
                
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

    # === 构建数据表格 ===
    table_data = []
    
    # [新功能] 全局报销人输入框
    st.markdown("##### 📝 填写报销信息")
    c_input, _ = st.columns([1, 3])
    with c_input:
        # 默认值为空，用户输入后会自动更新所有行的“报销人”列
        reimburser_name = st.text_input("报销人姓名 (统一填写)", placeholder="请输入名字", help="此处输入后将自动填充表格第一列")

    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        name = st.session_state.renamed_files.get(fid, f.name)
        # 获取用户之前填写的事项，默认为空
        desc = st.session_state.descriptions.get(fid, "")
        
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                d = cache['data']
                try: amt = float(str(d.get('Total', 0)).replace(',','').replace('元',''))
                except: amt = 0.0
                # 构造行数据，注意顺序
                table_data.append({
                    "报销人": reimburser_name,  # 第1列
                    "文件名": name,            # 第2列
                    "日期": d.get('Date',''),   # 第3列
                    "项目": d.get('Item',''),   # 第4列
                    "事项": desc,               # 第5列 (新)
                    "金额": amt,                # 第6列
                    "状态": "成功",             # 第7列
                    "file_id": fid
                })
            elif cache['status'] == 'failed':
                table_data.append({
                    "报销人": reimburser_name,
                    "文件名": name,
                    "日期": "失败",
                    "项目": f"❌ {cache.get('error','识别超时')}",
                    "事项": desc,
                    "金额": 0.0,
                    "状态": "失败",
                    "file_id": fid
                })

    st.session_state.current_table_data = table_data
    if table_data:
        st.divider()
        failed_rows = len([x for x in table_data if x['状态'] == "失败"])
        if failed_rows > 0:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning(f" 有 {failed_rows} 张文件识别失败。")
            with c2: 
                if st.button(" 🔄 重试所有未完成任务", type="primary", use_container_width=True):
                    for r in table_data:
                        if r['状态'] == '失败':
                            st.session_state.processed_session_ids.discard(r['file_id'])
                    st.rerun()

        # 配置列的属性
        df = pd.DataFrame(table_data)
        column_cfg = {
            "file_id": None, 
            "金额": st.column_config.NumberColumn(format="%.2f"),
            "状态": st.column_config.TextColumn(disabled=True),
            # 报销人设为只读，因为由上方输入框统一控制，避免歧义
            "报销人": st.column_config.TextColumn(disabled=True, width="medium"), 
            "文件名": st.column_config.TextColumn(disabled=False),
            # 事项列设为可编辑
            "事项": st.column_config.TextColumn(disabled=False, width="large", help="请在此处补充具体事项说明")
        }
        
        # 渲染表格，注意 DataFrame 的列顺序已经通过 append 字典的顺序决定了
        # 但为了保险，我们可以显式指定列顺序
        cols_order = ["报销人", "文件名", "日期", "项目", "事项", "金额", "状态", "file_id"]
        df = df[cols_order]
        
        edited_df = st.data_editor(
            df,
            column_config=column_cfg,
            use_container_width=True, 
            key="invoice_editor", 
            on_change=on_table_change
        )
        
        # === 底部合计与按钮区域 ===
        total_amt = df[df['状态'] == "成功"]['金额'].sum()
        out = io.BytesIO()
        exp_df = df.drop(columns=['file_id'])
        # 合计行只在“项目”列写合计，在“金额”列写数字
        total_row = [''] * len(exp_df.columns)
        # 找到列的索引位置
        idx_item = exp_df.columns.get_loc("项目")
        idx_amt = exp_df.columns.get_loc("金额")
        total_row[idx_item] = '合计'
        total_row[idx_amt] = total_amt
        
        exp_df.loc[len(exp_df)] = total_row
        with pd.ExcelWriter(out, engine='openpyxl') as writer: exp_df.to_excel(writer, index=False)

        col_left, col_center, col_right = st.columns([2, 5, 2])
        with col_center:
            inner_c1, inner_c2 = st.columns([0.65, 0.35], vertical_alignment="bottom")
            with inner_c1:
                st.markdown(f'''
                    <div class="total-display">
                        <span class="total-label">合计</span>
                        <span>{total_amt:,.2f}</span>
                    </div>
                ''', unsafe_allow_html=True)
            with inner_c2:
                st.download_button(
                    label="导出 Excel", 
                    data=out.getvalue(), 
                    file_name="发票汇总.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
else:
    st.info("👆 请上传发票文件。系统将自动开启全速识别。")
