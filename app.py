import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import io
from pdf2image import convert_from_bytes
import json

# --- 1. 配置新版 AI ---
# 请保留你的 API KEY
GOOGLE_API_KEY = "你的_API_KEY" 

client = genai.Client(api_key=GOOGLE_API_KEY)

def analyze_image(image_bytes, mime_type):
    """发送图片给 AI 提取数据 (新版 SDK 写法)"""
    prompt = """
    你是一个财务发票识别助手。请分析这张图片，提取以下三个字段：
    1. 发票项目名称 (Item) - 如果有多个，概括为一个主要项目。
    2. 开票日期 (Date) - 格式统一为 YYYY-MM-DD。
    3. 价税合计 (Total) - 纯数字，不要货币符号。
    
    请严格以 JSON 格式返回，不要包含 ```json 等标记，直接返回大括号内容。
    格式示例: {"Item": "办公用品", "Date": "2023-10-12", "Total": 100.50}
    """
    
    try:
        # 这里换回最稳的 1.5 Flash，配合新 SDK 一定能识别
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                    ]
                )
            ]
        )
        
        # 清洗数据
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"AI 响应错误: {e}")
        return None

# --- 2. 页面布局 ---
st.set_page_config(page_title="极速发票助手", layout="wide")
st.title("🧾 AI 智能发票汇总神器 (2026 新版)")
st.info("已升级至 Google GenAI 新版 SDK。支持 JPG/PNG/PDF。")

# --- 3. 文件上传区 ---
uploaded_files = st.file_uploader("拖入发票文件 (支持批量)", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    st.subheader("📊 识别结果")
    
    data_list = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for index, file in enumerate(uploaded_files):
        status_text.text(f"正在处理: {file.name} ...")
        file_bytes = file.read()
        target_image_bytes = file_bytes
        mime_type = file.type
        
        try:
            if file.type == "application/pdf":
                images = convert_from_bytes(file_bytes)
                if images:
                    img_byte_arr = io.BytesIO()
                    images[0].save(img_byte_arr, format='JPEG')
                    target_image_bytes = img_byte_arr.getvalue()
                    mime_type = "image/jpeg"
            
            result = analyze_image(target_image_bytes, mime_type)
            
            if result:
                try:
                    amount = float(str(result.get('Total', 0)).replace(',',''))
                except:
                    amount = 0.0
                
                data_list.append({
                    "文件名": file.name,
                    "开票日期": result.get('Date', ''),
                    "发票项目": result.get('Item', ''),
                    "价税合计": amount
                })
                # 成功提示
                st.toast(f"✅ {file.name} 识别成功!", icon="🎉")
                
        except Exception as e:
            st.error(f"处理 {file.name} 失败: {e}")

        progress_bar.progress((index + 1) / len(uploaded_files))
    
    status_text.text("✅ 所有文件处理完毕！")
    
    if data_list:
        df = pd.DataFrame(data_list)
        total_sum = df['价税合计'].sum()
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.dataframe(df, use_container_width=True)
        with col2:
            st.metric("💰 总金额", f"¥ {total_sum:,.2f}")
        
        df.loc[len(df)] = ['合计', '', '', total_sum]
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='发票汇总')
            
        st.download_button(
            label="📥 下载 Excel",
            data=output.getvalue(),
            file_name="发票汇总表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
