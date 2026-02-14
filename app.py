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
        margin-bottom: 20px; display: flex; gap: 20px; align-items: center;
    }
    .stat-item { font-size: 16px; font-weight: 500; }
    .stat-success { color: #28a745; }
    .stat-fail { color: #dc3545; }
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
        # 尝试调用
        result = call_api_once(image_bytes, mime_type, log_container)
        
        if result:
            return result # 成功直接返回
        
        # 如果失败，且不是最后一次，则进入重试倒计时
        if attempt < MAX_RETRIES:
            wait_time = attempt * 2 # 第一次等2秒，第二次等4秒
            log_container.warning(f"⚠️ 识别失败，正在进行第 {attempt} 次自动重试 (等待 {wait_time}s)...")
            time.sleep(wait_time)
        else:
            log_container.error("❌ 3次重试均失败，放弃处理。")
    
    return None

# --- 5. 页面主程序 ---
st.set_page_config(page_title="AI 发票助手", layout="wide")
st.title("🧾 AI 发票助手 (智能重试版)")

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
        
        # 逻辑：(不在缓存 OR 缓存是失败状态) AND (本轮还没尝试过)
        is_cached = fid in st.session_state.invoice_cache
        is_failed_before = is_cached and st.session_state.invoice_cache[fid].get('status') == 'failed'
        has_tried_this_session = fid in st.session_state.processed_session_ids
        
        if (not is_cached or is_failed_before) and not has_tried_this_session:
            queue_to_process.append(f)

    # === 2. 批量处理循环 ===
    if queue_to_process:
        with st.status("🚀 正在执行识别任务...", expanded=True) as status_box:
            total = len(queue_to_process)
            progress_bar = st.progress(0) # 显式初始化进度条
            current_log = st.empty()
            
            for i, file in enumerate(queue_to_process):
                fid = f"{file.name}_{file.size}"
                st.session_state.processed_session_ids.add(fid) # 标记已处理
                
                # 更新状态栏文案
                status_box.update(label=f"正在处理 ({i+1}/{total}): {file.name}")
                current_log.info(f"📄 正在读取第 {i+1} 张：`{file.name}`")
                
                try:
                    # 读取文件
                    file.seek(0)
                    f_bytes = file.read()
                    m_type = file.type
                    if m_type == "application/pdf":
                        current_log.markdown("&nbsp;&nbsp;&nbsp;&nbsp;📄 PDF 转图片中...")
                        images = convert_from_bytes(f_bytes)
                        if images:
                            buf = io.BytesIO()
                            images[0].save(buf, format="JPEG")
                            f_bytes, m_type = buf.getvalue(), "image/jpeg"
                    elif m_type == 'image/jpg': m_type = 'image/jpeg'

                    # 调用带重试的函数
                    result = analyze_with_retry(f_bytes, m_type, current_log)
                    
                    if result:
                        st.session_state.invoice_cache[fid] = {'status': 'success', 'data': result}
                        current_log.success(f"✅ `{file.name}` 识别成功！")
                    else:
                        st.session_state.invoice_cache[fid] = {'status': 'failed'}
                
                except Exception as e:
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
                    current_log.error(f"❌ 异常: {e}")

                # 更新进度条
                progress_bar.progress((i + 1) / total)
                
            status_box.update(label="✅ 本轮任务处理完毕！", state="complete", expanded=False)
            time.sleep(1)
            st.rerun()

    # === 3. 数据统计与常驻看板 (解决统计消失问题) ===
    # 基于当前缓存计算实时统计，而不是依赖临时变量
    table_data = []
    failed_files_count = 0
    success_files_count = 0
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        cache = st.session_state.invoice_cache.get(fid)
        if cache:
            if cache['status'] == 'success':
                success_files_count += 1
                res = cache['data']
                try: amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
                except: amt = 0.0
                table_data.append({"文件名": file.name, "日期": res.get('Date',''), "项目": res.get('Item',''), "金额": amt, "状态": "✅ 成功", "file_id": fid})
            elif cache['status'] == 'failed':
                failed_files_count += 1
                table_data.append({"文件名": file.name, "日期": "-", "项目": "-", "金额": 0.0, "状态": "❌ 失败", "file_id": fid})

    # 🟢 常驻统计看板 (放在表格上方)
    if uploaded_files:
        st.markdown(f"""
            <div class="dashboard-box">
                <div class="stat-item">📂 文件总数: {len(table_data)}</div>
                <div class="stat-item stat-success">✅ 识别成功: {success_files_count}</div>
                <div class="stat-item stat-fail">❌ 识别失败: {failed_files_count}</div>
            </div>
        """, unsafe_allow_html=True)

    # === 4. 表格与操作 ===
    if table_data:
        df = pd.DataFrame(table_data)
        
        # 失败手动重试区
        if failed_files_count > 0:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning(f"⚠️ 有 {failed_files_count} 张文件经过 3 次自动重试后仍失败，请检查文件或网络后点击右侧按钮。")
            with c2: 
                if st.button("🔄 手工重试失败任务", type="primary", use_container_width=True):
                    # 从已处理名单中移除，触发重新处理
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
        
        # 同步修改金额
        for index, row in edited_df.iterrows():
            fid = row['file_id']
            if fid in st.session_state.invoice_cache and st.session_state.invoice_cache[fid]['status'] == 'success':
                 st.session_state.invoice_cache[fid]['data']['Total'] = row['金额']

        # === 5. 底部总金额与导出 ===
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
