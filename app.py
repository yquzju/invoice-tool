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
# 备选模型
CANDIDATE_MODELS = ["Qwen/Qwen2-VL-72B-Instruct", "Qwen/Qwen2-VL-7B-Instruct"]

# --- 2. 注入 CSS：按钮样式、居中对齐、状态列样式 ---
st.markdown("""
    <style>
    /* 下载按钮样式 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.2rem !important;
        border-radius: 8px !important;
        transition: all 0.3s ease;
        width: auto !important;
        min-width: unset !important;
        display: inline-flex !important;
        font-weight: 500 !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 12px rgba(0,123,255,0.3) !important;
    }
    /* 去除按钮图标 */
    button[data-testid="baseButton-primary"] p::before { content: none !important; }

    /* 底部布局容器 */
    .total-container {
        display: flex;
        align-items: baseline;
        justify-content: flex-end;
        gap: 15px;
        height: 100%;
    }
    .total-label { font-size: 1.2rem; color: #6C757D; }
    .total-value { font-size: 2rem; font-weight: 700; color: #212529; }
    </style>
""", unsafe_allow_html=True)

# --- 3. 核心识别函数 ---
def analyze_invoice(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    # 提示词：强制要求提取价税合计
    prompt = "Extract invoice data into JSON: 1.Item (Name), 2.Date (YYYY-MM-DD), 3.Total (Amount including tax/价税合计). JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"

    for model in CANDIDATE_MODELS:
        data = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "max_tokens": 512, "temperature": 0.1
        }
        try:
            resp = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if resp.status_code == 200:
                content = resp.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except: continue
    return None

# --- 4. 页面逻辑 ---
st.set_page_config(page_title="发票助手 (稳健版)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 稳健版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # --- 1. 预处理：找出真正需要识别的新文件 ---
    # 逻辑：不在缓存里 且 不在忽略列表里，或者 在缓存里但是状态是“失败”的（需要重试）
    files_to_process = []
    for f in uploaded_files:
        fid = f"{f.name}_{f.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 如果缓存里没有，或者缓存里记录的是失败，都加入待处理队列
        if fid not in st.session_state.invoice_cache or st.session_state.invoice_cache[fid].get('status') == 'failed':
            files_to_process.append(f)

    # --- 2. 批量识别 ---
    if files_to_process:
        # 显示重试或新任务的提示
        msg_text = f"正在处理 {len(files_to_process)} 张发票..."
        info_box = st.info(msg_text)
        progress_bar = st.progress(0)
        
        for i, file in enumerate(files_to_process):
            fid = f"{file.name}_{file.size}"
            
            try:
                # 文件转字节流
                file.seek(0) # 确保从头读取
                f_bytes = file.read()
                m_type = file.type
                
                if m_type == "application/pdf":
                    images = convert_from_bytes(f_bytes)
                    if images:
                        buf = io.BytesIO()
                        images[0].save(buf, format="JPEG")
                        f_bytes, m_type = buf.getvalue(), "image/jpeg"
                elif m_type == 'image/jpg': 
                    m_type = 'image/jpeg'

                # 调用识别
                result = analyze_image(f_bytes, m_type)
                
                if result:
                    # 成功：写入缓存
                    st.session_state.invoice_cache[fid] = {
                        'status': 'success',
                        'data': result
                    }
                else:
                    # 失败：也写入缓存，标记为失败
                    st.session_state.invoice_cache[fid] = {'status': 'failed'}
            
            except Exception as e:
                st.session_state.invoice_cache[fid] = {'status': 'failed'}
            
            # 更新进度 & ⏳ 防封号延迟
            progress_bar.progress((i + 1) / len(files_to_process))
            time.sleep(1.0) # 休息1秒，防止并发过快导致报错
            
        info_box.empty()
        progress_bar.empty()
        st.rerun() # 处理完强制刷新，确保表格显示最新状态

    # --- 3. 构建表格数据 ---
    table_data = []
    has_failure = False
    
    for file in uploaded_files:
        fid = f"{file.name}_{file.size}"
        if fid in st.session_state.ignored_files: continue
        
        # 从缓存读取状态
        cache = st.session_state.invoice_cache.get(fid)
        
        if cache and cache['status'] == 'success':
            res = cache['data']
            try:
                amt = float(str(res.get('Total', 0)).replace(',','').replace('元',''))
            except: amt = 0.0
            
            table_data.append({
                "文件名": file.name,
                "日期": res.get('Date', ''),
                "项目": res.get('Item', ''),
                "金额": amt,
                "状态": "✅ 成功",
                "file_id": fid
            })
        elif cache and cache['status'] == 'failed':
            has_failure = True
            table_data.append({
                "文件名": file.name,
                "日期": "-",
                "项目": "-",
                "金额": 0.0,
                "状态": "❌ 失败", # 显式显示失败
                "file_id": fid
            })
        else:
            # 极少数情况：刚上传还没处理完
            pass

    # --- 4. 渲染表格与按钮 ---
    if table_data:
        df = pd.DataFrame(table_data)
        
        # 如果有失败的任务，显示“重试”按钮
        if has_failure:
            col_warn, col_retry = st.columns([8, 2])
            with col_warn:
                st.warning("⚠️ 检测到有发票识别失败，请检查网络或点击右侧按钮重试。")
            with col_retry:
                if st.button("🔄 重试失败任务", type="primary", use_container_width=True):
                    # 逻辑：页面刷新时，上面的 files_to_process 逻辑会自动捕捉到 status='failed' 的任务并重试
                    st.rerun()

        # 可编辑表格
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None,
                "金额": st.column_config.NumberColumn(format="%.2f"),
                "状态": st.column_config.TextColumn(width="small", disabled=True),
                "文件名": st.column_config.TextColumn(disabled=True)
            },
            num_rows="dynamic",
            use_container_width=True,
            key="invoice_editor"
        )
        
        # 删除与同步逻辑
        current_ids = set(edited_df["file_id"])
        original_ids = set(df["file_id"])
        if len(current_ids) != len(original_ids):
            deleted = original_ids - current_ids
            st.session_state.ignored_files.update(deleted)
            st.rerun()
            
        # 实时更新修改后的数据到缓存
        for index, row in edited_df.iterrows():
            fid = row['file_id']
            # 只更新成功的记录
            if fid in st.session_state.invoice_cache and st.session_state.invoice_cache[fid]['status'] == 'success':
                 st.session_state.invoice_cache[fid]['data']['Total'] = row['金额']
                 st.session_state.invoice_cache[fid]['data']['Date'] = row['日期']
                 st.session_state.invoice_cache[fid]['data']['Item'] = row['项目']

        # --- 5. 底部布局（保持您要求的样式） ---
        total = edited_df[edited_df['状态'] == "✅ 成功"]['金额'].sum()
        
        col_space1, col_content, col_space2 = st.columns([2.5, 5, 2.5])
        with col_content:
            sub_l, sub_r = st.columns([1.5, 1])
            with sub_l:
                st.markdown(f"""
                    <div class="total-container">
                        <span class="total-label">💰 总金额合计</span>
                        <span class="total-value">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            with sub_r:
                output = io.BytesIO()
                df_export = edited_df.drop(columns=["file_id"])
                df_export.loc[len(df_export)] = ['合计', '', '', total, '']
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False)
                
                st.download_button("导出 excel", output.getvalue(), "发票汇总.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
