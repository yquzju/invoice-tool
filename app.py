import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- 填入你的 SiliconFlow Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" [cite: 1]

# --- 备选模型名单 ---
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct",       # 优先尝试大模型
    "Qwen/Qwen2-VL-7B-Instruct",        # 备选小模型
    "deepseek-ai/deepseek-vl-7b-chat",
    "TeleAI/TeleMM"
] [cite: 1]

API_URL = "https://api.siliconflow.cn/v1/chat/completions" [cite: 1]

# --- 🟢 新增：注入 CSS 实现按钮样式定制与水平居中对齐 ---
st.markdown("""
    <style>
    /* 1. 定制下载按钮样式：高级蓝、动态适配大小、去除图标 */
    div.stDownloadButton > button {
        background-color: #007bff !important; /* 高级蓝色 */
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.2rem !important; /* 动态适配文案大小 */
        border-radius: 8px !important;
        transition: all 0.3s ease;
        width: auto !important; /* 宽度不撑满 */
        min-width: unset !important; /* 取消最小宽度限制 */
        display: inline-flex !important;
        font-weight: 500 !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 12px rgba(0,123,255,0.3) !important;
    }
    /* 去除下载按钮自带的图标 */
    button[data-testid="baseButton-primary"] p::before {
        content: none !important;
    }

    /* 2. 居中对齐容器 */
    .footer-align-container {
        display: flex;
        align-items: baseline; /* 基准线对齐，确保文案和按钮平齐 */
        justify-content: center; /* 水平居中 */
        gap: 15px; /* 文案与按钮的间距 */
        margin-top: 30px;
        margin-bottom: 20px;
    }
    .total-text {
        font-size: 1.2rem;
        color: #6C757D;
    }
    .total-val {
        font-size: 2rem;
        font-weight: 700;
        color: #212529;
    }
    </style>
""", unsafe_allow_html=True)

def analyze_image_auto_switch(image_bytes, mime_type):
    """自动轮询模型，直到成功"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8') [cite: 1]
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json" [cite: 1, 2]
    }
    
    last_error = ""

    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f" 正在尝试: {model_name} ...") [cite: 2]
        
        data = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract invoice data into JSON: 1.Item 2.Date 3.Total. JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"}, [cite: 3, 4]
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 512,
            "temperature": 0.1 [cite: 4, 5]
        }

        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45) [cite: 5]
            
            if response.status_code == 200:
                status_placeholder.empty()
                content = response.json()['choices'][0]['message']['content'] [cite: 5, 6]
                clean = content.replace("```json", "").replace("```", "").strip() [cite: 6]
                s = clean.find('{')
                e = clean.rfind('}') + 1
                return json.loads(clean[s:e]) if s != -1 else json.loads(clean) [cite: 6]
            
            elif response.status_code == 403: [cite: 7]
                status_placeholder.empty()
                if "7B" in model_name:
                    raise Exception("余额不足，请检查 SiliconFlow 账号。") [cite: 7]
                continue
            else:
                status_placeholder.empty() [cite: 8]
                continue

        except Exception as e:
            status_placeholder.empty()
            last_error = str(e) [cite: 8]
            continue
            
    raise Exception(f"所有模型均不可用。最后报错: {last_error}") [cite: 8]

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (可编辑版)", layout="wide") [cite: 8]
st.title(" 发票助手 (QwenVL 可编辑版)") [cite: 8]

# 1. 初始化记忆缓存
if 'invoice_cache' not in st.session_state: [cite: 9]
    st.session_state.invoice_cache = {} [cite: 9]

# 新增：初始化已删除文件列表
if 'ignored_files' not in st.session_state: [cite: 9]
    st.session_state.ignored_files = set() [cite: 9]

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True) [cite: 9]

if uploaded_files:
    st.divider() [cite: 9]
    
    # 筛选出需要处理的新文件（排除已缓存的 和 已被用户删除的）
    new_files = []
    for file in uploaded_files:
        file_id = f"{file.name}_{file.size}" [cite: 9]
        # 只有当它既没在缓存里，也没在删除列表里，才算新文件
        if file_id not in st.session_state.invoice_cache and file_id not in st.session_state.ignored_files:
            new_files.append(file) [cite: 9, 10]
    
    if new_files:
        progress_bar = st.progress(0) [cite: 10]
        st.info(f"检测到 {len(new_files)} 张新发票，准备开始识别...") [cite: 10]
    
    current_data_list = []
    
    # === 主循环：准备显示的数据 ===
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}" [cite: 10]
        
        # 如果这个文件之前被用户删除了，就跳过不显示
        if file_id in st.session_state.ignored_files: [cite: 11]
            continue [cite: 11]

        # 检查缓存
        if file_id in st.session_state.invoice_cache: [cite: 11]
            result = st.session_state.invoice_cache[file_id] [cite: 11]
        else:
            try:
                # 识别逻辑
                file_bytes = file.read() [cite: 12]
                process_bytes = file_bytes
                mime_type = file.type [cite: 12]
                
                if file.type == "application/pdf": [cite: 12]
                    images = convert_from_bytes(file_bytes) [cite: 12]
                    if images: [cite: 13]
                        img_buffer = io.BytesIO()
                        images[0].save(img_buffer, format="JPEG") [cite: 13]
                        process_bytes = img_buffer.getvalue() [cite: 13]
                        mime_type = "image/jpeg" [cite: 14]
                if mime_type == 'image/jpg': mime_type = 'image/jpeg' [cite: 14]

                result = analyze_image_auto_switch(process_bytes, mime_type) [cite: 14]
                
                if result:
                    st.session_state.invoice_cache[file_id] = result [cite: 15]
                    st.toast(f" {file.name} 识别成功") [cite: 15]
                
                if file in new_files:
                    curr_progress = (new_files.index(file) + 1) / len(new_files) [cite: 16]
                    progress_bar.progress(curr_progress) [cite: 16]

            except Exception as e:
                st.error(f" {file.name} 失败: {e}") [cite: 16]
                result = None [cite: 16]

        # 整理数据
        if result:
            try: [cite: 17]
                raw_amt = str(result.get('Total', 0)).replace('','').replace(',','').replace('元','') [cite: 17]
                amt = float(raw_amt) [cite: 17]
            except:
                amt = 0.0 [cite: 17]
            
            current_data_list.append({
                "文件名": file.name, [cite: 18]
                "日期": result.get('Date', ''), [cite: 18]
                "项目": result.get('Item', ''), [cite: 18]
                "金额": amt, [cite: 18]
                "file_id": file_id # 埋入隐形ID，用于追踪编辑和删除 [cite: 18]
            })

    # === 结果展示与编辑 ===
    if current_data_list: [cite: 19]
        df = pd.DataFrame(current_data_list) [cite: 19]
        
        st.caption(" 提示：您可以直接在下方表格中 **修改内容**，或选中行并按 Delete 键(或点击右侧垃圾桶) **删除行**。") [cite: 19]
        
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None, # 隐藏 ID 列，用户看不到 [cite: 20]
                "金额": st.column_config.NumberColumn(format="%.2f"), [cite: 20]
                "文件名": st.column_config.TextColumn(disabled=True) # 文件名设为只读，防止改乱 [cite: 20]
            },
            num_rows="dynamic", # 允许增删行 [cite: 20]
            use_container_width=True, [cite: 20]
            key="invoice_editor" [cite: 21]
        )
        
        # === 同步逻辑：处理用户的编辑和删除 ===
        
        # 1. 识别被删除的行
        original_ids = set(df["file_id"]) [cite: 21]
        current_ids = set(edited_df["file_id"]) [cite: 21]
        deleted_ids = original_ids - current_ids [cite: 21, 22]
        
        if deleted_ids:
            st.session_state.ignored_files.update(deleted_ids) [cite: 22]
            st.rerun() [cite: 22]

        # 2. 识别被修改的行，并反向更新缓存
        for index, row in edited_df.iterrows(): [cite: 22]
            fid = row['file_id'] [cite: 23]
            if fid in st.session_state.invoice_cache: [cite: 23]
                cached_item = st.session_state.invoice_cache[fid] [cite: 23]
                cached_item['Date'] = row['日期'] [cite: 23]
                cached_item['Item'] = row['项目'] [cite: 24]
                cached_item['Total'] = row['金额'] [cite: 24]

        # === 🟢 核心修改：居中同行布局展示 ===
        total = edited_df['金额'].sum() [cite: 24]
        
        # 准备 Excel 导出数据
        df_export = edited_df.drop(columns=["file_id"]) [cite: 24]
        df_export.loc[len(df_export)] = ['合计', '', '', total] [cite: 25]
        output = io.BytesIO() [cite: 25]
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False) [cite: 25]
            
        # 使用 3 列布局 [留白, 内容, 留白] 实现整体水平居中
        col_side1, col_content, col_side2 = st.columns([2.5, 5, 2.5])
        
        with col_content:
            # 使用内嵌 columns 进一步精细化对齐
            sub_left, sub_right = st.columns([1.5, 1])
            
            with sub_left:
                # 渲染金额文案，向右对齐以靠近按钮
                st.markdown(f"""
                    <div style="display: flex; align-items: baseline; justify-content: flex-end; gap: 10px; height: 100%;">
                        <span class="total-text">💰 总金额合计</span>
                        <span class="total-val">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            
            with sub_right:
                # 渲染按钮：按钮会自动靠左，紧跟在金额数值右边
                st.download_button(
                    label="导出 excel", # 修改文案
                    data=output.getvalue(), [cite: 26]
                    file_name="发票汇总.xlsx", [cite: 26]
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" [cite: 26]
                )
