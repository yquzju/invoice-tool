import time
import streamlit as st
import pandas as pd
import requests
import base64
import json
import io
from pdf2image import convert_from_bytes

# --- ⚠️ 唯一需要手动填的地方 ---
API_KEY = "AIzaSyARtowfN-m9H80rbXgpXGBR-xZQIzp8LSg"  # <--- 请务必填入你的 AIza 开头的 Key

def get_available_model_url():
    """
    自动侦测当前 API Key 可用的模型
    不再盲猜名字，而是直接问服务器
    """
    try:
        # 1. 获取模型列表
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
        response = requests.get(list_url)
        
        if response.status_code != 200:
            st.error(f"无法获取模型列表，请检查 API Key 是否正确。错误代码: {response.status_code}")
            return None

        models = response.json().get('models', [])
        
        # 2. 筛选出支持生成内容 (generateContent) 的模型
        candidates = []
        for m in models:
            methods = m.get('supportedGenerationMethods', [])
            name = m.get('name', '')
            if 'generateContent' in methods:
                # 排除一些不需要的视觉模型或旧模型
                if 'vision' not in name and 'embedding' not in name:
                    candidates.append(name)
        
        if not candidates:
            st.error("未找到任何可用模型！")
            return None

        # 3. 智能优选：优先找 flash，其次找 pro，最后随便拿一个
        selected_model = candidates[0] # 默认拿第一个
        
        # 优先匹配逻辑
        for name in candidates:
            if 'flash' in name and '2.0' not in name: # 避开额度紧张的 2.0
                selected_model = name
                break
            if 'pro' in name and '1.5' in name:
                selected_model = name
                break
        
        # 去掉 'models/' 前缀（如果 URL 里不需要的话，但通常 v1beta 调用时需要保留或处理，这里我们用全路径）
        # 构建最终调用 URL
        # 注意：name 格式通常是 "models/gemini-1.5-flash"
        clean_name = selected_model.replace("models/", "")
        final_url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_name}:generateContent?key={API_KEY}"
        
        return final_url, clean_name

    except Exception as e:
        st.error(f"自动寻址失败: {e}")
        return None, None

def analyze_image_auto(image_bytes, mime_type, api_url):
    """
    使用自动获取的 URL 进行识别
    """
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [
                {"text": "Extract 3 fields into JSON:\n1. Item (Main product name, keep Chinese)\n2. Date (YYYY-MM-DD)\n3. Total (Number only)\n\nFormat: {\"Item\": \"...\", \"Date\": \"...\", \"Total\": 0.0}"},
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
        response = requests.post(api_url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result_json = response.json()
            text_content = result_json['candidates'][0]['content']['parts'][0]['text']
            clean_text = text_content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text)
        else:
            # 如果报错，打印出来看
            st.warning(f"当前模型请求失败 ({response.status_code})，尝试下一个...")
            return None
            
    except Exception as e:
        st.error(f"请求异常: {e}")
        return None

# --- 页面主逻辑 ---
st.set_page_config(page_title="全自动发票助手", layout="wide")
st.title("🧾 AI 智能发票汇总 (自适应版)")

# 初始化时自动寻找模型
if 'model_url' not in st.session_state:
    with st.spinner("正在自动寻找最合适的 AI 模型..."):
        url, name = get_available_model_url()
        if url:
            st.session_state['model_url'] = url
            st.session_state['model_name'] = name
            st.success(f"✅ 已连接至模型: **{name}**")
        else:
            st.stop()

st.info(f"当前使用模型: `{st.session_state.get('model_name', '未知')}` (自动匹配)")

uploaded_files = st.file_uploader("请上传发票", type=['png', 'jpg', 'jpeg', 'pdf'], accept_multiple_files=True)

if uploaded_files:
    st.divider()
    data_list = []
    progress_bar = st.progress(0)
    
    for index, file in enumerate(uploaded_files):
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

            # 使用自动获取的 URL
            result = analyze_image_auto(process_bytes, mime_type, st.session_state['model_url'])
            
            if result:
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
            else:
                 st.error(f"❌ {file.name} 识别失败 (模型未返回数据)")

        except Exception as e:
            st.error(f"处理 {file.name} 异常: {e}")
        time.sleep(3)  # 强制休息 3 秒，防止触发 429 限速
            
        progress_bar.progress((index + 1) / len(uploaded_files))

    if data_list:
        df = pd.DataFrame(data_list)
        total = df['价税合计'].sum()
        st.dataframe(df, use_container_width=True)
        st.metric("💰 总计", f"¥ {total:,.2f}")
        # ---这里是补全的代码---
        
        # 1. 准备导出的数据（增加一行“合计”）
        df_export = df.copy()
        df_export.loc[len(df_export)] = ['合计', '', '', total]
        
        # 2. 写入 Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False)
            
        # 3. 显示下载按钮
        st.download_button(
            label="📥 下载 Excel 表格",
            data=output.getvalue(),
            file_name="发票汇总.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"  # 这会让按钮变成醒目的红色/主色调
        )
