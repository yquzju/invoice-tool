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
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct", "TeleAI/TeleMM"]

# --- 2. 注入 CSS ---
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
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .stat-item { font-size: 16px; font-weight: 600; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
    
    /* 正在处理的文件高亮 */
    .processing-highlight { color: #007bff; font-weight: bold; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 单次 API 请求函数 ---
def call_api_once(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    for model in CANDIDATE_MODELS:
        if log_placeholder: log_placeholder.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;🔄 正在连接模型 `{model}`...")
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

# --- 4. 核心：带自动重试的识别逻辑 ---
def analyze_with_retry(image_bytes, mime_type, log_container):
    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        result = call_api_once(image_bytes, mime_type, log_container)
        if result: return result 
        
        if attempt < MAX_RETRIES:
            wait_time = attempt * 2 
            log_container.warning(f"⚠️ 识别失败，正在进行第 {attempt} 次自动重试 (等待 {wait_time}s)...")
            time.sleep(wait_time)
        else:
            log_container.error("❌ 3次重试均失败，放弃处理。")
    return None

# --- 5. 页面主程序 ---
st.set_page_config(page_title="AI 发票助手", layout="wide")
st.title("🧾 AI 发票助手 (可视化全开版)")

# 初始化 Session
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # === 1. 计算待处理队列 ===
    queue_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        is_cached = fid in st.session_state.invoice_cache
        is_failed_before = is_cached and st.session_state.invoice_cache[fid].get('status') == 'failed'
        has_tried_this_session = fid in st.session_state.processed_session_ids
        
        if (not is_cached or is_failed_before) and not has_tried_this_session:
            queue_to_process.append(f)

    # === 🟢 2. 全局常驻看板 (实时显示状态) ===
    # 统计逻辑：遍历所有 uploaded_files 结合 cache 计算
    total_files = len(uploaded_files)
    success_count = 0
    fail_count = 0
    
    # 预计算当前的成功失败数 (包含还没处理完的中间态)
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.invoice_cache:
            status = st.session_state.invoice_cache[fid].get('status')
            if status == 'success': success_count += 1
            elif status == 'failed': fail_count += 1
    
    # 创建看板占位符，用于循环中动态更新
    dashboard_placeholder = st.empty()
    
    def render_dashboard(s_count, f_count):
        dashboard_placeholder.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item">📂 文件总数: {total_files}</div>
                <div class="stat-item stat-success">✅ 识别成功: {s_count}</div>
                <div class="stat-item stat-fail">❌ 识别失败: {f_count}</div>
                <div class="stat-item" style="color:#666">⏳ 待处理: {total_files - s_count - f_count}</div>
            </div>
        """, unsafe_allow_html=True)
    
    render_dashboard(success_count, fail_count)

    # === 3. 批量处理循环 (直接在主界面显示进度) ===
    if queue_to_process:
        st.write("---") # 分割线
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_area = st.empty() # 专门显示连接模型的日志
        
        for i, file in enumerate(queue_to_process):
            fid = f"{file.name}_{file.size}"
            st.session_state.processed_session_ids.add(fid)
            
            # 更新状态提示
            status_text.markdown(f"<div class='processing-highlight'>🚀 正在处理第 {i+1}/{len(queue_to_process)} 张：{file.name}</div>", unsafe_allow_html=True)
            
            try:
                file.seek(0)
                f_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    log_area.caption("📄 PDF 转图片中...")
                    images = convert_from_bytes(f_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                elif m_type == 'image/jpg': m_type = 'image/jpeg'

                # 调用带重试的函数
                result = analyze_with_retry(f_bytes, m_type, log_area)
                
                if result:
                    st.session_state.invoice_cache[fid] = {'status': 'success', 'data': result}
                    success_count += 1 # 实时更新计数
                    log_area.success(f"✅ {file.name} 识别成功")
                else:
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
                    fail_count += 1 # 实时更新计数
            
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed'}
                fail_count += 1

            # 🟢 实时更新看板数字
            render_dashboard(success_count, fail_count)
            # 更新进度条
            progress_bar.progress((i + 1) / len(queue_to_process))
            time.sleep(0.5) # 视觉缓冲

        # 循环结束清理
        status_text.empty()
        log_area.empty()
        progress_bar.empty()
        st.rerun()

    # === 4. 表格数据准备 ===
    table_data = []
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                res = cache['data']
                try: amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
                except: amt = 0.0
                table_data.append({"文件名": file.name, "日期": res.get('Date',''), "项目": res.get('Item',''), "金额": amt, "状态": "✅ 成功", "file_id": fid})
            elif cache['status'] == 'failed':
                table_data.append({"文件名": file.name, "日期": "-", "项目": "-", "金额": 0.0, "状态": "❌ 失败", "file_id": fid})

    # === 5. 表格与操作 ===
    if table_data:
        df = pd.DataFrame(table_data)
        
        # 失败手动重试区
        failed_rows = len([x for x in table_data if x['状态'] == "❌ 失败"])
        if failed_rows > 0:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning(f"⚠️ 有 {failed_rows} 张文件自动重试失败，请点击右侧按钮进行最后一搏。")
            with c2: 
                if st.button("🔄 手工重试失败任务", type="primary", use_container_width=True):
                    for fid in st.session_state.processed_session_ids.copy():
                        if st.session_state.invoice_cache.get(fid, {}).get('status') == 'failed':
                            st.session_state.processed_session_ids.remove(fid)
                    st.rerun()

        # 表格
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None, "金额": st.column_config.NumberColumn(format="%.2f"),
                "状态": st.column_config.TextColumn(width="small", disabled=True),
                "文件名": st.column_config.TextColumn(disabled=True)
            },
            num_rows="dynamic", use_container_width=True, key="invoice_editor"
        )
        
        # 同步逻辑
        current_ids = set(edited_df["file_id"])
        original_ids = set(df["file_id"])
        if len(current_ids) != len(original_ids):
            st.session_state.ignored_files.update(original_ids - current_ids)
            st.rerun()
            
        for index, row in edited_df.iterrows():
            fid = row['file_id']
            if fid in st.session_state.invoice_cache and st.session_state.invoice_cache[fid]['status'] == 'success':
                 st.session_state.invoice_cache[fid]['data']['Total'] = row['金额']

        # === 6. 底部总金额与导出 ===
        total = edited_df[edited_df['状态'] == "✅ 成功"]['金额'].sum()
        c_s1, c_main, c_s2 = st.columns([2.5, 5, 2.5])
        with c_main:
            i_l, i_r = st.columns([1.5, 1])
            with i_l:
                st.markdown(f"""<div class="total-container"><span class="total-label">💰 总金额合计</span><span class="total-value">¥ {total:,.2f}</span></div>""", unsafe_allow_html=True)
            with i_r:
                out = io.BytesIO()
                exp = edited_df.drop(columns=["file_id"])
                exp.loc[len(exp)] = ['合计', '', '', total, '']
                with pd.ExcelWriter(out, engine='openpyxl') as writer: exp.to_excel(writer, index=False)
                st.download_button("导出 excel", out.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
