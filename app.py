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
    div.stDownloadButton > button {
        background-color: #007bff !important; color: white !important; border: none !important;
        padding: 0.5rem 1.2rem !important; border-radius: 8px !important; width: auto !important;
    }
    div.stDownloadButton > button:hover { background-color: #0056b3 !important; }
    button[data-testid="baseButton-primary"] p::before { content: none !important; }
    .total-container { display: flex; align-items: baseline; justify-content: flex-end; gap: 15px; }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 核心识别函数 ---
def analyze_invoice(image_bytes, mime_type, log_placeholder):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Grand Total including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    for model in CANDIDATE_MODELS:
        if log_placeholder: log_placeholder.markdown(f"&nbsp;&nbsp;🔄 正在连接模型：`{model}` ...")
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
            elif resp.status_code == 429: # 限流
                if log_placeholder: log_placeholder.warning(f"⚠️ 触发限流 (429)，正在冷却 2秒...")
                time.sleep(2)
        except Exception: continue
    return None

# --- 4. 页面主程序 ---
st.set_page_config(page_title="AI 发票助手", layout="wide")
st.title("🧾 AI 发票助手 (可视化控制台版)")

# 初始化 Session State
if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()
# 关键：记录本轮会话已尝试过的文件，防止死循环自动重试
if 'processed_session_ids' not in st.session_state: st.session_state.processed_session_ids = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 1. 智能筛选：只处理 (未缓存 OR 缓存失败) AND (本轮未尝试过) 的文件
    queue_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 核心逻辑：如果文件不在缓存里，或者之前失败了，且本轮还没试过，加入队列
        is_cached = fid in st.session_state.invoice_cache
        is_failed_before = is_cached and st.session_state.invoice_cache[fid].get('status') == 'failed'
        has_tried_this_session = fid in st.session_state.processed_session_ids
        
        if (not is_cached or is_failed_before) and not has_tried_this_session:
            queue_to_process.append(f)

    # 2. 批量处理队列
    if queue_to_process:
        with st.status("🚀 正在执行批量识别任务...", expanded=True) as status_box:
            total_tasks = len(queue_to_process)
            success_count = 0
            fail_count = 0
            
            # 进度条与状态显示
            progress_bar = st.progress(0)
            stats_text = st.empty()
            current_log = st.empty()
            
            for i, file in enumerate(queue_to_process):
                fid = f"{file.name}_{file.size}"
                # 标记该文件本轮已尝试，无论成败，防止死循环
                st.session_state.processed_session_ids.add(fid)
                
                # 更新面板信息
                stats_text.markdown(f"📊 **进度**: 成功 `{success_count}` | 失败 `{fail_count}` | 剩余 `{total_tasks - i}`")
                status_box.update(label=f"正在处理 ({i+1}/{total_tasks}): {file.name}")
                current_log.info(f"📄 正在读取: `{file.name}`")
                
                try:
                    file.seek(0)
                    f_bytes = file.read()
                    m_type = file.type
                    
                    if m_type == "application/pdf":
                        current_log.markdown("&nbsp;&nbsp;📄 PDF 转图片中...")
                        images = convert_from_bytes(f_bytes)
                        if images:
                            buf = io.BytesIO()
                            images[0].save(buf, format="JPEG")
                            f_bytes, m_type = buf.getvalue(), "image/jpeg"
                    elif m_type == 'image/jpg': m_type = 'image/jpeg'

                    # 调用识别
                    result = analyze_invoice(f_bytes, m_type, current_log)
                    
                    if result:
                        st.session_state.invoice_cache[fid] = {'status': 'success', 'data': result}
                        current_log.success(f"✅ `{file.name}` 识别成功！")
                        success_count += 1
                    else:
                        st.session_state.invoice_cache[fid] = {'status': 'failed'}
                        current_log.error(f"❌ `{file.name}` 识别失败 (已跳过)")
                        fail_count += 1
                
                except Exception as e:
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
                    current_log.error(f"❌ 异常错误: {e}")
                    fail_count += 1

                progress_bar.progress((i + 1) / total_tasks)
                time.sleep(1.0) # 强制冷却，防止最后一张被限流

            # 循环结束
            final_msg = f"✅ 处理结束！成功 {success_count} 张，失败 {fail_count} 张。"
            if fail_count > 0:
                final_msg += " (失败文件已标记在表格中)"
            status_box.update(label=final_msg, state="complete", expanded=False)
            time.sleep(1.5)
            st.rerun()

    # --- 3. 结果展示 ---
    table_data = []
    failed_files = [] # 收集失败文件供重试
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        cache = st.session_state.invoice_cache.get(fid)
        
        if cache and cache['status'] == 'success':
            res = cache['data']
            try: amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
            except: amt = 0.0
            table_data.append({
                "文件名": file.name, "日期": res.get('Date', ''), "项目": res.get('Item', ''), 
                "金额": amt, "状态": "✅ 成功", "file_id": fid
            })
        elif cache and cache['status'] == 'failed':
            failed_files.append(fid)
            table_data.append({
                "文件名": file.name, "日期": "-", "项目": "-", 
                "金额": 0.0, "状态": "❌ 失败", "file_id": fid
            })

    if table_data:
        df = pd.DataFrame(table_data)
        
        # 失败重试区
        if failed_files:
            c1, c2 = st.columns([8, 2])
            with c1: st.warning(f"⚠️ 有 {len(failed_files)} 张发票识别失败。您可以检查网络后，点击右侧按钮单独重试这些文件。")
            with c2: 
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True):
                    # 核心逻辑：从“已处理集合”中移除这些ID，下次循环就会重新处理它们
                    for fid in failed_files:
                        if fid in st.session_state.processed_session_ids:
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

        # 底部栏
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
