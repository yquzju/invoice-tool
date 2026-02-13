import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- ⚠️ 填入你的 SiliconFlow Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# --- 备选模型名单 ---
CANDIDATE_MODELS = [
    "Qwen/Qwen2-VL-72B-Instruct",       # 优先尝试大模型
    "Qwen/Qwen2-VL-7B-Instruct",        # 备选小模型
    "deepseek-ai/deepseek-vl-7b-chat",
    "TeleAI/TeleMM"
]

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

def analyze_image_auto_switch(image_bytes, mime_type):
    """自动轮询模型，直到成功"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    last_error = ""

    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在尝试: {model_name} ...")
        
        data = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract invoice data into JSON: 1.Item 2.Date 3.Total. JSON format: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 512,
            "temperature": 0.1
        }

        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45)
            
            if response.status_code == 200:
                status_placeholder.empty()
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s = clean.find('{')
                e = clean.rfind('}') + 1
                return json.loads(clean[s:e]) if s != -1 else json.loads(clean)
            
            elif response.status_code == 403:
                status_placeholder.empty()
                if "7B" in model_name:
                    raise Exception("余额不足，请检查 SiliconFlow 账号。")
                continue
            else:
                status_placeholder.empty()
                continue

        except Exception as e:
            status_placeholder.empty()
            last_error = str(e)
            continue
            
    raise Exception(f"所有模型均不可用。最后报错: {last_error}")

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (可编辑版)", layout="wide")
st.title("🧾 发票助手 (QwenVL 可编辑版)")

# 1. 初始化记忆缓存
if 'invoice_cache' not in st.session_state:
    st.session_state.invoice_cache = {}

# 🟢 新增：初始化“已删除文件”列表
if 'ignored_files' not in st.session_state:
    st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    # 筛选出需要处理的新文件（排除已缓存的 和 已被用户删除的）
    new_files = []
    for file in uploaded_files:
        file_id = f"{file.name}_{file.size}"
        # 只有当它既没在缓存里，也没在删除列表里，才算新文件
        if file_id not in st.session_state.invoice_cache and file_id not in st.session_state.ignored_files:
            new_files.append(file)
    
    if new_files:
        progress_bar = st.progress(0)
        st.info(f"检测到 {len(new_files)} 张新发票，准备开始识别...")
    
    current_data_list = []
    
    # === 主循环：准备显示的数据 ===
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        
        # 🟢 如果这个文件之前被用户删除了，就跳过不显示
        if file_id in st.session_state.ignored_files:
            continue

        # 检查缓存
        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
        else:
            try:
                # 识别逻辑
                file_bytes = file.read()
                process_bytes = file_bytes
                mime_type = file.type
                
                if file.type == "application/pdf":
                    images = convert_from_bytes(file_bytes)
                    if images:
                        img_buffer = io.BytesIO()
                        images[0].save(img_buffer, format="JPEG")
                        process_bytes = img_buffer.getvalue()
                        mime_type = "image/jpeg"
                if mime_type == 'image/jpg': mime_type = 'image/jpeg'

                result = analyze_image_auto_switch(process_bytes, mime_type)
                
                if result:
                    st.session_state.invoice_cache[file_id] = result
                    st.toast(f"✅ {file.name} 识别成功")
                
                if file in new_files:
                    curr_progress = (new_files.index(file) + 1) / len(new_files)
                    progress_bar.progress(curr_progress)

            except Exception as e:
                st.error(f"❌ {file.name} 失败: {e}")
                result = None

        # 整理数据
        if result:
            try:
                raw_amt = str(result.get('Total', 0)).replace('¥','').replace(',','').replace('元','')
                amt = float(raw_amt)
            except:
                amt = 0.0
            
            current_data_list.append({
                "文件名": file.name,
                "日期": result.get('Date', ''),
                "项目": result.get('Item', ''),
                "金额": amt,
                "file_id": file_id # 🟢 埋入隐形ID，用于追踪编辑和删除
            })

    # === 结果展示与编辑 ===
    if current_data_list:
        df = pd.DataFrame(current_data_list)
        
        # 🟢 核心修改：使用 data_editor 代替 dataframe
        st.caption("✨ 提示：您可以直接在下方表格中 **修改内容**，或选中行并按 Delete 键(或点击右侧垃圾桶) **删除行**。")
        
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None, # 隐藏 ID 列，用户看不到
                "金额": st.column_config.NumberColumn(format="%.2f"),
                "文件名": st.column_config.TextColumn(disabled=True) # 文件名设为只读，防止改乱
            },
            num_rows="dynamic", # 🟢 允许增删行
            use_container_width=True,
            key="invoice_editor"
        )
        
        # === 🟢 同步逻辑：处理用户的编辑和删除 ===
        
        # 1. 识别被删除的行
        # 对比原始 ID 和 编辑后的 ID，找出少了谁
        original_ids = set(df["file_id"])
        current_ids = set(edited_df["file_id"])
        deleted_ids = original_ids - current_ids
        
        if deleted_ids:
            # 将删除的文件ID加入“黑名单”，防止下次刷新又跳出来
            st.session_state.ignored_files.update(deleted_ids)
            # 立即刷新页面，让删除效果更干脆
            st.rerun()

        # 2. 识别被修改的行，并反向更新缓存
        # 这样你修改了金额后，下载 Excel 也是改好的金额
        for index, row in edited_df.iterrows():
            fid = row['file_id']
            # 如果缓存里有这个文件，更新它的数据
            if fid in st.session_state.invoice_cache:
                cached_item = st.session_state.invoice_cache[fid]
                # 只有当数据真的变了才更新（虽然直接赋值也没问题）
                cached_item['Date'] = row['日期']
                cached_item['Item'] = row['项目']
                cached_item['Total'] = row['金额']

        # === 统计与下载 (使用编辑后的 edited_df) ===
        
        total = edited_df['金额'].sum()
        st.metric("💰 总金额", f"¥ {total:,.2f}")
        
        # 导出 Excel (去掉隐藏的 file_id 列)
        df_export = edited_df.drop(columns=["file_id"])
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        st.download_button(
            label="📥 下载 Excel 表格 (包含修改)", 
            data=output.getvalue(), 
            file_name="发票汇总.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
