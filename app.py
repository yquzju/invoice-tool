import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes
import time

# --- ⚠️ 填入你刚才在 SiliconFlow 申请的 sk- 开头的 Key ---
API_KEY = "sk-epvburmeracnfubnwswnzspuylzuajtoncrdsejqefjlrmtw" 

# --- 配置：使用通义千问 Qwen2-VL (中文 OCR 最强王者) ---
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2-VL-72B-Instruct"  # 72B 是超大杯模型，识别极准

def analyze_image_qwen(image_bytes, mime_type):
    """
    使用 Qwen2-VL 进行发票识别
    (通过 OpenAI 兼容接口)
    """
    # 1. 图片转 Base64
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 2. 构建标准 OpenAI 格式请求
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": "请提取这张发票图片中的：1.发票项目名称(Item) 2.开票日期(Date, YYYY-MM-DD) 3.价税合计(Total, 纯数字)。请直接返回 JSON 格式，例如：{\"Item\": \"服务费\", \"Date\": \"2023-01-01\", \"Total\": 100.00}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1 # 温度越低越准确
    }

    # 3. 发送请求 (带简单的重试)
    for attempt in range(3):
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                res_json = response.json()
                content = res_json['choices'][0]['message']['content']
                
                # 清洗 JSON
                clean_content = content.replace("```json", "").replace("```", "").strip()
                # 这是一个容错逻辑，防止模型返回包含解释性文字
                start_idx = clean_content.find('{')
                end_idx = clean_content.rfind('}') + 1
                if start_idx != -1 and end_idx != -1:
                    clean_content = clean_content[start_idx:end_idx]
                    
                return json.loads(clean_content)
            else:
                st.warning(f"请求失败 ({response.status_code}): {response.text}")
                time.sleep(2)
                
        except Exception as e:
            st.error(f"网络连接错误: {e}")
            time.sleep(2)
            
    return None

# --- 页面逻辑 ---
st.set_page_config(page_title="发票助手 (Qwen版)", layout="wide")
st.title("🧾 AI 发票助手 (Qwen2-VL 强力版)")
st.success("🚀 已切换至 Qwen2-VL-72B 模型。中文识别能力极强，且无 Google 限速烦恼。")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
        try:
            # 文件处理
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

            # 调用 Qwen
            result = analyze_image_qwen(process_bytes, mime_type)
            
            if result:
                try:
                    # 金额清洗
                    raw_amt = str(result.get('Total', 0))
                    # 去掉中文货币符号和逗号
                    raw_amt = raw_amt.replace('¥', '').replace('￥', '').replace(',', '').replace('元', '')
                    amt = float(raw_amt)
                except:
                    amt = 0.0
                
                data_list.append({
                    "文件名": file.name,
                    "开票日期": result.get('Date', ''),
                    "发票项目": result.get('Item', ''),
                    "价税合计": amt
                })
                st.toast(f"✅ {file.name} 识别成功")
            else:
                 st.error(f"❌ {file.name} 识别失败")

        except Exception as e:
            st.error(f"系统异常: {e}")
            
        progress_bar.progress((index + 1) / len(uploaded_files))

    # 导出 Excel
    if data_list:
        df = pd.DataFrame(data_list)
        total = df['价税合计'].sum()
        
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        
        df_export = df.copy()
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        st.download_button("📥 下载 Excel 表格", output.getvalue(), "发票汇总.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
