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
    "Qwen/Qwen2-VL-72B-Instruct",
    "Qwen/Qwen2-VL-7B-Instruct",
    "deepseek-ai/deepseek-vl-7b-chat",
    "TeleAI/TeleMM"
]

API_URL = "https://api.siliconflow.cn/v1/chat/completions"

# --- 注入 CSS 实现高级感 UI 与右侧同行布局 ---
st.markdown("""
    <style>
    /* 1. 定制下载按钮样式：高级蓝色 */
    div.stDownloadButton > button {
        background-color: #007bff !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1.5rem !important;
        border-radius: 8px !important;
        transition: all 0.3s ease;
        font-weight: 500 !important;
        width: auto !important; /* 宽度自适应 */
    }
    div.stDownloadButton > button:hover {
        background-color: #0056b3 !important;
        box-shadow: 0 4px 12px rgba(0,123,255,0.3) !important;
    }
    
    /* 2. 同行对齐容器：确保金额和按钮在视觉中线对齐 */
    .alignment-container {
        display: flex;
        align-items: center; /* 垂直居中对齐 */
        justify-content: flex-end; /* 水平靠右对齐 */
        gap: 20px; /* 文案与按钮的间距 */
        margin-top: 10px;
    }

    .total-label-inline {
        font-size: 1.1rem;
        color: #6C757D;
        white-space: nowrap;
    }
    .total-value-inline {
        font-size: 1.8rem;
        font-weight: 700;
        color: #212529;
        white-space: nowrap;
    }
    </style>
""", unsafe_allow_html=True)

def analyze_image_auto_switch(image_bytes, mime_type):
    """自动轮询模型识别"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在尝试: {model_name} ...")
        
        data = {
            "model": model_name,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Extract invoice: {\"Item\":\"x\",\"Date\":\"x\",\"Total\":0}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
            ]}],
            "temperature": 0.1
        }
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=45)
            if response.status_code == 200:
                status_placeholder.empty()
                content = response.json()['choices'][0]['message']['content']
                clean = content.replace("```json", "").replace("```", "").strip()
                s, e = clean.find('{'), clean.rfind('}') + 1
                return json.loads(clean[s:e])
        except:
            status_placeholder.empty()
            continue
    return None

# --- 页面逻辑 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide")
st.title("🧾 AI 发票助手 (QwenVL 可编辑版)")

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

uploaded_files = st.file_uploader("请上传发票文件", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    current_data_list = []
    
    for index, file in enumerate(uploaded_files):
        file_id = f"{file.name}_{file.size}"
        if file_id in st.session_state.ignored_files: continue

        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
        else:
            try:
                file_bytes = file.read()
                m_type = file.type
                if m_type == "application/pdf":
                    img = convert_from_bytes(file_bytes)[0]
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    file_bytes, m_type = buf.getvalue(), "image/jpeg"
                
                result = analyze_image_auto_switch(file_bytes, m_type)
                if result: st.session_state.invoice_cache[file_id] = result
            except: result = None

        if result:
            amt = float(str(result.get('Total', 0)).replace('¥','').replace(',',''))
            current_data_list.append({
                "文件名": file.name, "日期": result.get('Date', ''),
                "项目": result.get('Item', ''), "金额": amt, "file_id": file_id
            })

    if current_data_list:
        df = pd.DataFrame(current_data_list)
        edited_df = st.data_editor(
            df,
            column_config={"file_id": None, "金额": st.column_config.NumberColumn(format="%.2f")},
            num_rows="dynamic", use_container_width=True, key="invoice_editor"
        )
        
        # 同步删除逻辑
        deleted_ids = set(df["file_id"]) - set(edited_df["file_id"])
        if deleted_ids:
            st.session_state.ignored_files.update(deleted_ids)
            st.rerun()

        # --- 🟢 核心修改：同行布局 [金额 + 按钮 靠右] ---
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 准备导出 Excel 逻辑 (需放在布局前以便按钮调用)
        total = edited_df['金额'].sum()
        df_export = edited_df.drop(columns=["file_id"])
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
        
        # 创建布局：左侧 70% 留空，右侧 30% 放置内容
        col_left, col_right = st.columns([7, 3])
        
        with col_right:
            # 使用 Flex 布局让金额文案和下载按钮在同一行
            # 我们通过 st.container + 内部两列或直接 HTML 来精细控制
            inner_col1, inner_col2 = st.columns([1.2, 1])
            
            with inner_col1:
                # 渲染总金额文本
                st.markdown(f"""
                    <div style="text-align: right; line-height: 1.2;">
                        <span class="total-label-inline">💰 总计金额</span><br>
                        <span class="total-value-inline">¥ {total:,.2f}</span>
                    </div>
                """, unsafe_allow_html=True)
            
            with inner_col2:
                # 渲染下载按钮
                st.download_button(
                    label="📥 下载 excel", 
                    data=output.getvalue(), 
                    file_name="发票汇总.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
