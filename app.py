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

# --- 样式美化 (CSS) ---
def local_css():
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .stApp {
        background-color: #F5F7F9;
    }

    /* 隐藏上传组件自带列表 */
    [data-testid='stFileUploader'] section > div:nth-child(2) {
        display: none !important;
    }
    [data-testid='stFileUploader'] {
        padding: 0;
    }
    div[data-testid="stFileUploaderDropzone"] {
        border: 2px dashed #d1d5db;
        border-radius: 12px;
        background-color: white;
        padding: 30px;
    }

    /* 统计卡片样式 */
    .metric-card-container {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
        color: white;
        height: 100px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        border: 1px solid rgba(0,0,0,0.05);
    }
    .card-title { font-size: 14px; opacity: 0.9; margin-bottom: 4px; }
    .card-value { font-size: 26px; font-weight: 700; }
    
    .bg-blue { background: #3B82F6; }
    .bg-green { background: #10B981; }
    .bg-orange { background: #F59E0B; }
    
    /* 底部按钮栏优化 */
    .stButton button {
        height: 45px;
        border-radius: 8px;
        font-weight: 600;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 核心识别逻辑 ---
def analyze_image_auto_switch(image_bytes, mime_type):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    last_error = ""

    for model_name in CANDIDATE_MODELS:
        status_placeholder = st.empty()
        status_placeholder.caption(f"🔄 正在通过 {model_name} 识别...")
        
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
                if "7B" in model_name: raise Exception("余额不足")
                continue
            else:
                status_placeholder.empty()
                continue
        except Exception as e:
            status_placeholder.empty()
            last_error = str(e)
            continue
    raise Exception(f"识别失败: {last_error}")

# --- 主页面逻辑 ---
st.set_page_config(page_title="AI 发票助手(QwenVL 版)", layout="wide", initial_sidebar_state="collapsed")
local_css()

if 'invoice_cache' not in st.session_state: st.session_state.invoice_cache = {}
if 'ignored_files' not in st.session_state: st.session_state.ignored_files = set()

st.markdown("### 🧾 AI 发票助手 (QwenVL 版)")

# 🟢 1. 先占位 (此时不填数据，等表格算完最新的再回来填)
top_card_container = st.container()

# 2. 上传区
uploaded_files = st.file_uploader("点击或拖拽上传发票 (支持 PDF/JPG/PNG)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

# 3. 数据准备
current_data_list = []
if uploaded_files:
    valid_files = [f for f in uploaded_files if f"{f.name}_{f.size}" not in st.session_state.ignored_files]
    new_files = [f for f in valid_files if f"{f.name}_{f.size}" not in st.session_state.invoice_cache]
    
    if new_files:
        st.write(f"🚀 正在识别 {len(new_files)} 张新发票...")
        progress_bar = st.progress(0)
    
    for index, file in enumerate(valid_files):
        file_id = f"{file.name}_{file.size}"
        
        if file_id in st.session_state.invoice_cache:
            result = st.session_state.invoice_cache[file_id]
            status = "✅ 完成"
        else:
            try:
                file_bytes = file.read()
                mime_type = file.type
                process_bytes = file_bytes
                
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
                    status = "✅ 完成"
                
                if file in new_files:
                    progress_bar.progress((new_files.index(file) + 1) / len(new_files))

            except Exception as e:
                result = None
                status = "❌ 失败"

        if result:
            try:
                amt = float(str(result.get('Total', 0)).replace('¥','').replace(',','').replace('元',''))
            except: amt = 0.0
            item_name = result.get('Item', '')
            date_str = result.get('Date', '')
        else:
            amt = 0.0
            item_name = "未识别"
            date_str = "-"
            
        current_data_list.append({
            "file_id": file_id,
            "序号": index + 1,
            "文件名": file.name,
            "项目名称": item_name,
            "开票时间": date_str,
            "金额": amt,
            "状态": status
        })

# --- 4. 渲染主表格并获取【最新】数据 ---
st.markdown("##### 📄 发票列表")

final_df = pd.DataFrame(columns=["序号", "文件名", "项目名称", "开票时间", "金额", "状态"])
total_amount_realtime = 0.0
total_count_realtime = 0
success_count_realtime = 0

if current_data_list:
    df = pd.DataFrame(current_data_list)
    
    # 🟢 核心：使用 edited_df 获取用户刚改完的数据
    edited_df = st.data_editor(
        df,
        column_config={
            "file_id": None,
            "序号": st.column_config.NumberColumn(width="small", disabled=True),
            "文件名": st.column_config.TextColumn(width="medium", disabled=True),
            "项目名称": st.column_config.TextColumn(width="medium"),
            "开票时间": st.column_config.TextColumn(width="small"),
            "金额": st.column_config.NumberColumn(format="¥ %.2f", width="small"),
            "状态": st.column_config.TextColumn(width="small", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="invoice_editor"
    )
    
    # 逻辑处理：删除
    current_ids = set(edited_df["file_id"])
    original_ids = set(df["file_id"])
    deleted_ids = original_ids - current_ids
    if deleted_ids:
        st.session_state.ignored_files.update(deleted_ids)
        st.rerun()

    # 逻辑处理：修改 (更新缓存)
    for index, row in edited_df.iterrows():
        fid = row['file_id']
        if fid in st.session_state.invoice_cache:
            cache = st.session_state.invoice_cache[fid]
            if cache['Item'] != row['项目名称'] or cache['Total'] != row['金额'] or cache['Date'] != row['开票时间']:
                cache['Item'] = row['项目名称']
                cache['Date'] = row['开票时间']
                cache['Total'] = row['金额']
    
    # 🟢 计算最新的实时总额 (基于 edited_df)
    final_df = edited_df
    total_amount_realtime = final_df['金额'].sum()
    total_count_realtime = len(final_df)
    success_count_realtime = len(final_df[final_df['状态'].str.contains("完成")])

else:
    st.dataframe(final_df, use_container_width=True, hide_index=True)
    st.caption("👆 请将文件拖入上方虚线框内")

# --- 🟢 5. 回头去填顶部的卡片 (使用实时算出来的数据) ---
with top_card_container:
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"""<div class="metric-card-container bg-blue"><div class="card-title">发票总数</div><div class="card-value">{total_count_realtime}</div></div>""", unsafe_allow_html=True)
    c2.markdown(f"""<div class="metric-card-container bg-green"><div class="card-title">识别成功</div><div class="card-value">{success_count_realtime}</div></div>""", unsafe_allow_html=True)
    # 这里显示的 total_amount_realtime 已经是包含用户修改后的金额了
    c3.markdown(f"""<div class="metric-card-container bg-orange"><div class="card-title">合计金额</div><div class="card-value">¥ {total_amount_realtime:,.2f}</div></div>""", unsafe_allow_html=True)


# --- 6. 底部操作栏 ---
st.markdown("<br>", unsafe_allow_html=True)
col_spacer, col_btns = st.columns([7, 3])

with col_btns:
    b_col1, b_col2 = st.columns(2)
    with b_col1:
        if st.button("🗑️ 清空全部", use_container_width=True):
            st.session_state.invoice_cache = {}
            st.session_state.ignored_files = set()
            st.rerun()
    with b_col2:
        if not final_df.empty:
            df_export = final_df.drop(columns=["file_id", "序号", "状态"])
            df_export.loc[len(df_export)] = ['合计', '', '', total_amount_realtime]
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_export.to_excel(writer, index=False)
            
            st.download_button(
                label="📥 下载 Excel",
                data=output.getvalue(),
                file_name="发票汇总.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
        else:
            st.download_button("📥 下载 Excel", b"", disabled=True, use_container_width=True)
