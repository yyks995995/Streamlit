import streamlit as st
from chat_downloader import ChatDownloader
from openai import OpenAI
import os

st.set_page_config(page_title="Twitch VOD 弹幕 AI 舆情分析", page_icon="🎮", layout="wide")

st.title("🎮 Twitch 录播(VOD) 弹幕舆情分析台")
st.markdown("通过输入 Twitch VOD 链接，一键抓取历史弹幕，并严格按照《DF海外 KOL 弹幕分析模型》生成结构化舆情报告。")

# 侧边栏：配置信息
with st.sidebar:
    st.header("⚙️ 全局设置")
    openai_api_key = st.text_input("填入你的 OpenAI API Key", type="password")
    model_choice = st.selectbox("选择大模型版本", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])
    st.markdown("---")
    st.markdown("### 📝 内置分析模板")
    st.info("已完全对齐《xQc弹幕分析》报告标准：\n1. 核心结论提取\n2. 观点分布与二级表达结构\n3. 弹幕结构总结\n4. 主播四象限归类 (玩法/情绪驱动)")

# 主界面：输入区
vod_url = st.text_input("📺 输入 Twitch VOD 链接 (例如: https://www.twitch.tv/videos/123456789)")
max_messages = st.number_input("📥 抓取弹幕数量上限 (建议 5000-10000 避免超出大模型理解上限)", min_value=100, max_value=50000, value=8000, step=1000)

if st.button("🚀 开始抓取并生成报告"):
    if not openai_api_key:
        st.error("请先在左侧配置 OpenAI API Key！")
        st.stop()
    if not vod_url:
        st.error("请输入 Twitch 链接！")
        st.stop()

    client = OpenAI(api_key=openai_api_key)

    # ================= 阶段 1：扒取弹幕 =================
    st.subheader("1️⃣ 正在抓取 Twitch 弹幕...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    chat_messages = []
    try:
        downloader = ChatDownloader()
        # 抓取录播弹幕
        chat = downloader.get_chat(vod_url, max_messages=max_messages)
        
        for i, message in enumerate(chat):
            time_str = message.get('time_text', '')
            author = message.get('author', {}).get('name', 'Unknown')
            text = message.get('message', '')
            # 过滤掉极短的纯符号，保留有意义的文本
            if len(text.strip()) > 1:
                chat_messages.append(f"[{time_str}] {author}: {text}")
            
            if i % 100 == 0:
                progress_bar.progress(min(i / max_messages, 1.0))
                status_text.text(f"已抓取 {i} 条有效弹幕...")
                
        progress_bar.progress(1.0)
        status_text.text(f"✅ 成功提取 {len(chat_messages)} 条弹幕！")
    except Exception as e:
        st.error(f"抓取失败，请检查链接是否有效: {str(e)}")
        st.stop()

    # 提供原文本下载
    raw_chat_text = "\n".join(chat_messages)
    st.download_button(
        label="📥 下载原始弹幕 (TXT文本)",
        data=raw_chat_text,
        file_name="twitch_vod_chat_raw.txt",
        mime="text/plain"
    )

    # ================= 阶段 2：AI 舆情分析 =================
    st.subheader("2️⃣ ChatGPT 深度分析中 (严格遵循内置模板)...")
    
    # 将你的 PDF 报告结构硬编码入 AI 的系统提示词中
    system_prompt = """你是一个专业的游戏行业 KOL 舆情分析专家。
你的任务是根据用户提供的 Twitch 录播弹幕（Chat Logs），严格按照提供的专业模板输出舆情分析报告。请保持客观、专业。

【必须严格遵循的 Markdown 输出格式】：

# [替换为主播名字] 弹幕分析

## 一、核心结论
总结该场直播最重要的3个结论。
* **结论1：** [核心发现，如：XXX成为直播互动核心节点]
  * [具体表现与数据支撑]
  * **启示：** [对产品发行的启示]
* **结论2：** [关于主播行为或内容节奏的发现]
  * [具体表现与典型弹幕]
  * **启示：** [启示]
* **结论3：** [关于 Gameplay 体验或产品讨论的发现]
  * [具体表现与典型弹幕]
  * **启示：** [启示]

## 二、核心观点分布
提取弹幕中最核心的 4-5 个观点进行拆解。

* **观点一「[核心主题词]」**（占比约 XX%）
  * **出现时间/场景：** [如：战斗阶段/开箱阶段]
  * **二级表达结构：**
    1. [类型1，如煽动型]：[列举2-3条典型原声弹幕]
    2. [类型2，如吐槽型]：[列举2-3条典型原声弹幕]
  * **观察：** [深度分析该观点的互动特征]
*(继续列举观点二、观点三...)*

**弹幕结构总结：**
[一句话总结，例如：整体呈现 娱乐事件驱动 >> Gameplay讨论 的特征]

## 三、主播类型四象限模型归类
基于弹幕表现，将主播定位在【玩法驱动 vs 情绪驱动】与【娱乐体验 vs 产品理解】的十字模型中。
* **所属象限：** [例如：娱乐体验 × 情绪驱动]
* **特征观察：** [解释其在此象限的依据]
* **典型弹幕：** [列举该象限的标志性弹幕]
"""
    
    # 截断以防超出 Token 限制 (保留约 10万字符，对 gpt-4o 绰绰有余)
    user_prompt = f"以下是该 VOD 的弹幕记录采样：\n\n{raw_chat_text[:100000]}"

    try:
        with st.spinner("AI 正在根据四象限模型和核心观点进行拆解，请稍等 1-2 分钟..."):
            response = client.chat.completions.create(
                model=model_choice,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4, # 较低温度保证分析格式的严谨性
                max_tokens=3000
            )
            
        analysis_result = response.choices[0].message.content
        st.success("✅ 舆情报告生成完毕！")
        
        st.markdown("---")
        st.markdown(analysis_result)
        
        st.download_button(
            label="📄 下载舆情分析报告 (Markdown / 可转 Word)",
            data=analysis_result,
            file_name="Twitch_Chat_Analysis_Report.md",
            mime="text/markdown"
        )
        
    except Exception as e:
        st.error(f"AI 分析阶段报错: {str(e)}")
