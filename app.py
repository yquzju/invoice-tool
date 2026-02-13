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

# --- 🟢 注入自定义 CSS：修改按钮为高级蓝色并适配大小 ---
st.markdown("""
    <style>
    /* 定制下载按钮样式 */
    div.stDownloadButton > button {
        background-color: #007bff !important; /* 高级深蓝色 */
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.5rem !important; /* 上下左右内边距 */
        border-radius: 8px !important;
        transition: all 0.3s ease;
        width: auto !important; /* 宽度动态适配文案 */
        display: inline-flex !important;
        font-weight: 500 !important;
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important; /* 悬停时颜色加深 */
        box-shadow: 0 4px 12px rgba(0, 123, 255, 0.3) !important;
        transform: translateY(-1px);
    }
    div.stDownloadButton > button:active {
        transform: translateY(0px);
    }
    </style>
""", unsafe_allow_html=True)

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
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 可编辑版)")

# 1. 初始化记忆缓存
if 'invoice_cache' not in st.session_state:
    st.session_state.invoice_cache = {}

# 初始化“已删除文件”列表
if 'ignored_files' not in st.session_state:
    st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票文件", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    
    new_files = []
    for file in uploaded_files:
        file_id = f"{file.name}_{file.size}"
        if file_id not in st.session_state.invoice_cache and file_id not in st.session_state.ignored_files:
            new_files.append(file)
    
    if new_files:
        progress_bar = st.progress(0)
        st.info(f"检测到 {len(new_files)} 张新发票，准备开始识别...")
    
    current_data_list = []
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        
        if file_id in st.session_state.ignored_files:
            continue

        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
        else:
            try:
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
                "file_id": file_id
            })

    if current_data_list:
        df = pd.DataFrame(current_data_list)
        
        st.caption("✨ 提示：您可以直接在下方表格中 **修改内容**，或选中行并按 Delete 键(或点击右侧垃圾桶) **删除行**。")
        
        edited_df = st.data_editor(
            df,
            column_config={
                "file_id": None,
                "金额": st.column_config.NumberColumn(format="¥ %.2f"),
                "文件名": st.column_config.TextColumn(disabled=True)
            },
            num_rows="dynamic",
            use_container_width=True,
            key="invoice_editor"
        )
        
        # 同步逻辑
        original_ids = set(df["file_id"])
        current_ids = set(edited_df["file_id"])
        deleted_ids = original_ids - current_ids
        
        if deleted_ids:
            st.session_state.ignored_files.update(deleted_ids)
            st.rerun()

        for index, row in edited_df.iterrows():
            fid = row['file_id']
            if fid in st.session_state.invoice_cache:
                cached_item = st.session_state.invoice_cache[fid]
                cached_item['Date'] = row['日期']
                cached_item['Item'] = row['项目']
                cached_item['Total'] = row['金额']

        # 统计与展示
        total = edited_df['金额'].sum()
        st.metric("💰 总金额合计", f"¥ {total:,.2f}")
        
        # 导出 Excel
        df_export = edited_df.drop(columns=["file_id"])
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        # 🟢 修改点：文案改为“下载 excel”，移除 type="primary" 依靠 CSS 控制颜色
        st.download_button(
            label="📥 下载 excel", 
            data=output.getvalue(), 
            file_name="发票汇总.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
