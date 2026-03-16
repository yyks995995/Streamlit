import streamlit as st
import requests
import re
from openai import OpenAI
import time

st.set_page_config(page_title="Twitch VOD 弹幕 AI 舆情分析", page_icon="🎮", layout="wide")

st.title("🎮 Twitch 录播(VOD) 弹幕舆情分析台")
st.markdown("通过输入 Twitch VOD 链接，一键抓取历史弹幕，并严格按照《DF海外 KOL 弹幕分析模型》生成结构化舆情报告。")

# ================= 核心抓取逻辑 (Twitch V5 API) =================
def get_vod_id(url):
    match = re.search(r'videos/(\d+)', url)
    return match.group(1) if match else None

def fetch_twitch_chat_v5(vod_id, max_msgs):
    """
    使用更底层的非 GQL 接口抓取 Twitch VOD 弹幕
    由于 Twitch GQL 经常根据 Client-ID 限制跨域或者部分视频，
    我们退而求其次，使用更原始、限制更少的 V5 风格接口模拟
    """
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    
    headers = {
        'Client-ID': client_id,
        'Accept': 'application/vnd.twitchtv.v5+json'
    }
    
    messages = []
    cursor = None
    
    # 每次请求大概返回 50-100 条数据
    max_loops = (int(max_msgs) // 50) + 10
    
    for _ in range(max_loops):
        # 构建 V5 请求 URL
        base_url = f"https://api.twitch.tv/v5/videos/{vod_id}/comments"
        url = f"{base_url}?cursor={cursor}" if cursor else base_url
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
        except Exception as e:
            raise Exception(f"网络请求失败: {e}")
            
        if response.status_code != 200:
            raise Exception(f"Twitch API 拒绝连接: HTTP {response.status_code}。请确认视频是否属于订阅者专享(Sub-only)或已被删除。")
            
        try:
            data = response.json()
        except:
            raise Exception("Twitch 返回数据格式异常。")
            
        comments = data.get("comments", [])
        if not comments:
            break
            
        for comment in comments:
            # 解析时间
            offset = comment.get("content_offset_seconds", 0)
            m, s = divmod(int(offset), 60)
            h, m = divmod(m, 60)
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
            
            # 解析作者
            commenter = comment.get("commenter", {})
            author = commenter.get("display_name", "Unknown") if commenter else "Unknown"
            
            # 解析消息体
            message_obj = comment.get("message", {})
            body = message_obj.get("body", "")
            
            if len(body.strip()) > 1:
                messages.append(f"[{time_str}] {author}: {body}")
                
            if len(messages) >= max_msgs:
                return messages
                
        # 获取下一页游标
        cursor = data.get("_next")
        if not cursor:
            break
            
        time.sleep(0.1)  # 防封控短暂停顿
            
    return messages

# ================= 界面与交互 =================
with st.sidebar:
    st.header("⚙️ 全局设置")
    default_key = st.secrets.get("OPENAI_API_KEY", "")
    openai_api_key = st.text_input("填入你的 OpenAI API Key", value=default_key, type="password")
    model_choice = st.selectbox("选择大模型版本", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])
    st.markdown("---")
    st.markdown("### 📝 内置分析模板")
    st.info("已完全对齐《xQc弹幕分析》报告标准：\n1. 核心结论提取\n2. 观点分布与二级表达结构\n3. 弹幕结构总结\n4. 主播四象限归类 (玩法/情绪驱动)")

vod_url = st.text_input("📺 输入 Twitch VOD 链接 (例如: https://www.twitch.tv/videos/2723303877)")
max_messages = st.number_input("📥 抓取弹幕数量上限", min_value=100, max_value=50000, value=8000, step=1000)

if st.button("🚀 开始抓取并生成报告"):
    if not openai_api_key:
        st.error("请先在左侧配置 OpenAI API Key！")
        st.stop()
        
    vod_id = get_vod_id(vod_url)
    if not vod_id:
        st.error("无法识别 VOD ID，请确认链接格式。")
        st.stop()

    client = OpenAI(api_key=openai_api_key)

    # ================= 阶段 1：扒取弹幕 =================
    st.subheader("1️⃣ 正在抓取 Twitch 弹幕...")
    
    with st.spinner("正在使用底层接口提取弹幕..."):
        try:
            chat_messages = fetch_twitch_chat_v5(vod_id, max_messages)
            if len(chat_messages) > 0:
                st.success(f"✅ 成功抓取了 {len(chat_messages)} 条弹幕数据！")
        except Exception as e:
            st.error(f"抓取发生异常: {str(e)}")
            st.stop()

    if len(chat_messages) == 0:
        st.warning(f"视频 {vod_id} 提取到的弹幕数为 0。\n可能的原因：\n1. 视频太老，弹幕记录已被 Twitch 清理\n2. 该主播设置了【仅订阅者(Sub-only)可见】\n3. 视频本身没有任何聊天记录。")
        st.stop()

    raw_chat_text = "\n".join(chat_messages)
    st.download_button(
        label="📥 下载原始弹幕 (TXT文本)",
        data=raw_chat_text,
        file_name=f"twitch_vod_{vod_id}_chat.txt",
        mime="text/plain"
    )

    # ================= 阶段 2：AI 分析 =================
    st.subheader("2️⃣ ChatGPT 分析中...")
    
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
    
    user_prompt = f"以下是该 VOD 的弹幕记录采样：\n\n{raw_chat_text[:80000]}"

    try:
        with st.spinner("AI 拆解中，预计需要 1 分钟..."):
            response = client.chat.completions.create(
                model=model_choice,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                max_tokens=3000
            )
            
        analysis_result = response.choices[0].message.content
        st.success("✅ 舆情报告生成完毕！")
        
        st.markdown("---")
        st.markdown(analysis_result)
        
        st.download_button(
            label="📄 下载舆情分析报告 (Markdown)",
            data=analysis_result,
            file_name=f"Twitch_Analysis_{vod_id}.md",
            mime="text/markdown"
        )
        
    except Exception as e:
        st.error(f"AI 分析阶段报错: {str(e)}")
