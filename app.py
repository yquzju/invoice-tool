import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 1. 配置区域 ---
# 【重要】请将此处替换为您真实的 API Key
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct", "TeleAI/TeleMM"]

# --- 2. 页面与 CSS 设置 ---
st.set_page_config(page_title="AI 发票助手", layout="wide")

st.markdown("""
    <style>
    /* 按钮与布局样式 */
    div.stDownloadButton > button {
        background-color: #007bff !important; color: white !important; border: none !important;
        padding: 0.5rem 1.2rem !important; border-radius: 8px !important; width: auto !important;
    }
    div.stDownloadButton > button:hover { background-color: #0056b3 !important; }
    button[data-testid="baseButton-primary"] p::before { content: none !important; }
    
    /* 底部总金额栏 */
    .total-container { display: flex; align-items: baseline; justify-content: flex-end; gap: 15px; }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    
    /* 顶部统计看板 */
    .dashboard-box {
        padding: 15px; border-radius: 10px; background-color: #f8f9fa; border: 1px solid #e9ecef;
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    
    /* 正在处理的文件高亮 */
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. Session 初始化 ---
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()
if 'renamed_files' not in st.session_state: st.session_state.renamed_files = {} # 新增：存储改名映射

# --- 4. 功能函数 ---

def call_api_once(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    for model in CANDIDATE_MODELS:
        if log_placeholder: log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp; 正在连接模型 `{model}`...")
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=30)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except Exception: continue
    return None

def analyze_with_retry(image_bytes, mime_type, log_container):
    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        result = call_api_once(image_bytes, mime_type, log_container)
        if result: return result 
        
        if attempt < MAX_RETRIES:
            wait_time = attempt * 2 
            log_container.warning(f" 识别失败，正在进行第 {attempt} 次自动重试 (等待 {wait_time}s)...")
            time.sleep(wait_time)
        else:
            log_container.error(" 3次重试均失败，放弃处理。")
    return None

# --- 5. 核心修复：表格回调函数 (解决“修改需点两次”问题) ---
def on_table_change():
    """
    当表格被编辑时立即触发，将修改同步回 session_state
    """
    state = st.session_state["invoice_editor"]
    
    # 1. 获取当前表格展示的 DataFrame (为了通过 index 找到 file_id)
    # 注意：这里我们不能直接读 st.data_editor 的返回值，因为回调发生在返回值更新之前
    # 我们必须依赖 session_state 中存储的上一份 table_data 映射关系
    # 但为了简单可靠，我们将 table_data 存储在 session_state 中
    current_data = st.session_state.get('current_table_data', [])
    
    # 处理修改
    for idx, changes in state["edited_rows"].items():
        row_idx = int(idx)
        if row_idx < len(current_data):
            fid = current_data[row_idx]['file_id']
            
            # A. 处理改名
            if "文件名" in changes:
                st.session_state.renamed_files[fid] = changes["文件名"]
            
            # B. 处理金额修改 (仅当状态为成功时)
            if "金额" in changes:
                if fid in st.session_state.invoice_cache:
                    st.session_state.invoice_cache[fid]['data']['Total'] = changes["金额"]
            
            # C. 处理日期/项目修改 (可选)
            if "日期" in changes and fid in st.session_state.invoice_cache:
                st.session_state.invoice_cache[fid]['data']['Date'] = changes["日期"]
            if "项目" in changes and fid in st.session_state.invoice_cache:
                st.session_state.invoice_cache[fid]['data']['Item'] = changes["项目"]

# --- 6. 主程序 ---
st.title(" AI 发票助手 (可视化全开版)")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # === 1. 计算待处理队列 ===
    queue_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        is_cached = fid in st.session_state.invoice_cache
        # 修复逻辑：不仅重试 failed，任何没 success 的如果被重置了 processed 标志，都应该重试
        status = st.session_state.invoice_cache.get(fid, {}).get('status')
        is_success = (status == 'success')
        
        has_tried_this_session = fid in st.session_state.processed_session_ids
        
        if not is_success and not has_tried_this_session:
            queue_to_process.append(f)

    # === 2. 全局看板 ===
    total_files = len(uploaded_files)
    success_count = 0
    fail_count = 0
    
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.invoice_cache:
            status = st.session_state.invoice_cache[fid].get('status')
            if status == 'success': success_count += 1
            elif status == 'failed': fail_count += 1
    
    dashboard_placeholder = st.empty()
    def render_dashboard(s_count, f_count):
        dashboard_placeholder.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item"> 文件总数: {total_files}</div>
                <div class="stat-item stat-success"> 识别成功: {s_count}</div>
                <div class="stat-item stat-fail"> 识别失败: {f_count}</div>
                <div class="stat-item" style="color:#666"> 待处理: {total_files - s_count - f_count}</div>
            </div>
        """, unsafe_allow_html=True)
    render_dashboard(success_count, fail_count)

    # === 3. 处理循环 ===
    if queue_to_process:
        st.write("---")
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_area = st.empty()
        
        for i, file in enumerate(queue_to_process):
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid)
            
            # 使用自定义文件名（如果有）或原始名
            display_name = st.session_state.renamed_files.get(fid, file.name)
            status_text.markdown(f"<div class='processing-highlight'> 正在处理：{display_name} ({i+1}/{len(queue_to_process)})</div>", unsafe_allow_html=True)
            
            try:
                # 文件预处理
                file.seek(0)
                f_bytes = file.read()
                m_type = file.type
                
                # PDF 转图片
                if m_type == "application/pdf":
                    log_area.caption(" PDF 转图片中...")
                    images = convert_from_bytes(f_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                elif m_type == 'image/jpg': m_type = 'image/jpeg'

                # 调用 API
                result = analyze_with_retry(f_bytes, m_type, log_area)
                
                if result:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': result}
                    success_count += 1
                    log_area.success(f" {display_name} 识别成功")
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
                    fail_count += 1
            
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed'}
                fail_count += 1

            render_dashboard(success_count, fail_count)
            progress_bar.progress((i + 1) / len(queue_to_process))
            time.sleep(0.1)

        status_text.empty()
        log_area.empty()
        progress_bar.empty()
        st.rerun()

    # === 4. 数据准备 (核心修复：支持改名和回显) ===
    table_data = []
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 获取显示名称
        display_name = st.session_state.renamed_files.get(fid, file.name)
        
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                res = cache['data']
                try: amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
                except: amt = 0.0
                table_data.append({
                    "文件名": display_name, 
                    "日期": res.get('Date',''), 
                    "项目": res.get('Item',''), 
                    "金额": amt, 
                    "状态": " 成功", 
                    "file_id": fid
                })
            elif cache['status'] == 'failed':
                table_data.append({
                    "文件名": display_name, 
                    "日期": "-", "项目": "-", "金额": 0.0, 
                    "状态": " 失败", 
                    "file_id": fid
                })
        else:
            # 对于尚未处理或等待处理的文件，也显示出来，以便可以改名
            table_data.append({
                "文件名": display_name,
                "日期": "", "项目": "", "金额": 0.0,
                "状态": " 待处理",
                "file_id": fid
            })

    # 将数据存入 session 以供回调函数使用
    st.session_state.current_table_data = table_data

    # === 5. 表格与操作 ===
    if table_data:
        df = pd.DataFrame(table_data)
        
        # 修复逻辑：统计所有未成功的任务（包括失败和待处理）
        not_success_rows = len([x for x in table_data if x['状态'].strip() != "成功"])
        
        # 布局
        c1, c2 = st.columns([7, 3])
        
        with c1:
            if not_success_rows > 0:
                st.warning(f" 当前有 {not_success_rows} 个任务未完成或失败。")
        
        with c2:
            # 修复逻辑：重试按钮处理所有非成功的任务
            if st.button("🔄 重试所有未完成任务", type="primary", use_container_width=True, disabled=(not_success_rows==0)):
                for fid in st.session_state.processed_session_ids.copy():
                    # 检查缓存状态
                    status = st.session_state.invoice_cache.get(fid, {}).get('status')
                    # 如果不是成功状态，则移除“已处理”标记，触发重跑
                    if status != 'success':
                        st.session_state.processed_session_ids.remove(fid)
                        # 可选：如果你想让它再次显示为“待处理”而不是“失败”，可以清除缓存状态
                        # if fid in st.session_state.invoice_cache: del st.session_state.invoice_cache[fid]
                st.rerun()

        # 表格渲染 (绑定回调)
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None, 
                "金额": st.column_config.NumberColumn(format="%.2f", required=True),
                "状态": st.column_config.TextColumn(width="small", disabled=True),
                "文件名": st.column_config.TextColumn(disabled=False, help="双击可修改文件名"), # 开启编辑
                "日期": st.column_config.TextColumn(disabled=False),
                "项目": st.column_config.TextColumn(disabled=False)
            },
            num_rows="dynamic", 
            use_container_width=True, 
            key="invoice_editor",
            on_change=on_table_change # 绑定回调，实现即时生效
        )
        
        # === 6. 底部总金额与导出 ===
        # 计算总金额时只算成功的
        total = 0.0
        for row in table_data:
            if row['状态'].strip() == "成功":
                total += row['金额']

        c_s1, c_main, c_s2 = st.columns([2.5, 5, 2.5])
        with c_main:
            i_l, i_r = st.columns([1.5, 1])
            with i_l:
                st.markdown(f"""<div class="total-container"><span class="total-label"> 总金额合计</span><span class="total-value"> {total:,.2f}</span></div>""", unsafe_allow_html=True)
            with i_r:
                out = io.BytesIO()
                # 导出时去掉 file_id
                exp = pd.DataFrame(table_data).drop(columns=["file_id"])
                exp.loc[len(exp)] = ['合计', '', '', total, '']
                with pd.ExcelWriter(out, engine='openpyxl') as writer: exp.to_excel(writer, index=False)
                st.download_button("导出 excel", out.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
