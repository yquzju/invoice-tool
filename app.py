import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes

# --- 1. 配置部分 ---
# 替换你的 API KEY
API_KEY = "AIzaSyARtowfN-m9H80rbXgpXGBR-xZQIzp8LSg" 

def analyze_image_via_http(image_bytes, mime_type):
    """
    使用原生 HTTP 请求直接调用 Gemini API
    绕过所有 SDK 版本和编码兼容性问题
    """
    # 1. 将图片转为 Base64 字符串
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 2. 准备请求 URL (使用最稳定的 gemini-1.5-flash)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}"
    
    # 3. 准备请求头和数据 (纯 JSON，通用性最强)
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [
                {"text": "Extract these 3 fields from the invoice image into JSON:\n1. Item (Main product name, keep Chinese)\n2. Date (YYYY-MM-DD)\n3. Total (Number only)\n\nFormat: {\"Item\": \"...\", \"Date\": \"...\", \"Total\": 0.0}"},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64_image
                    }
                }
            ]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            st.error(f"API 请求失败 ({response.status_code}): {response.text}")
            return None
            
        # 解析返回结果
        result_json = response.json()
        text_content = result_json['candidates'][0]['content']['parts'][0]['text']
        
        # 清洗 Markdown 标记
        clean_text = text_content.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
        
    except Exception as e:
        st.error(f"处理出错: {str(e)}")
        return None

# --- 2. 页面主逻辑 ---
st.set_page_config(page_title="通用发票助手", layout="wide")
st.title("🧾 AI 智能发票汇总 (HTTP 通用版)")
st.info("已切换至原生 HTTP 模式，彻底解决环境兼容性问题。")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        try:
            # 文件预处理
            file_bytes = file.read()
            process_bytes = file_bytes
            mime_type = file.type
            
            # PDF 转图逻辑
            if file.type == "application/pdf":
                images = convert_from_bytes(file_bytes)
                if images:
                    img_buffer = io.BytesIO()
                    images[0].save(img_buffer, format="JPEG")
                    process_bytes = img_buffer.getvalue()
                    mime_type = "image/jpeg"
            
            # 统一将 image/jpg 转为 image/jpeg (API 偏好)
            if mime_type == 'image/jpg':
                mime_type = 'image/jpeg'

            # 调用 AI
            result = analyze_image_via_http(process_bytes, mime_type)
            
            if result:
                # 容错处理：确保金额是数字
                try:
                    amt = float(str(result.get('Total', 0)).replace('¥','').replace(',',''))
                except:
                    amt = 0.0
                
                data_list.append({
                    "文件名": file.name,
                    "开票日期": result.get('Date', ''),
                    "发票项目": result.get('Item', ''),
                    "价税合计": amt
                })
                st.toast(f"✅ {file.name} 成功")
                
        except Exception as e:
            st.error(f"{file.name} 失败: {e}")
            
        progress_bar.progress((index + 1) / len(uploaded_files))

    # 生成表格
    if data_list:
        df = pd.DataFrame(data_list)
        total = df['价税合计'].sum()
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        
        # 导出 Excel
        df.loc[len(df)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel", output.getvalue(), "发票汇总.xlsx")
