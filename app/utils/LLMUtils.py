# 作者：北小菜
# 官网：https://www.yuturuishi.com
# 微信：bilibili_bxc
# 哔哩哔哩主页：https://space.bilibili.com/487906612
# gitee地址：https://gitee.com/Vanishi/rebucca
# github地址：https://github.com/beixiaocai/rebucca
import base64

from openai import OpenAI


class LLMUtils:
    """大模型 API 工具（OpenAI 兼容视觉推理 / 文本对话）"""

    def __init__(self, api_url, api_key=None, timeout=15, inference_tool="OpenAI",
                 model="gpt-4o"):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout
        self.inference_tool = inference_tool or "OpenAI"
        self.model = model

    def __client(self):
        return OpenAI(api_key=self.api_key, base_url=self.api_url, timeout=self.timeout)

    def infer(self, prompt, image_bytes):
        if self.inference_tool != "OpenAI":
            raise Exception(f"不支持的推理工具: {self.inference_tool}")
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        response = self.__client().chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.choices[0].message.content

    @staticmethod
    def check_happen(result, happen_words):
        if not result or not happen_words:
            return False
        words = [w.strip() for w in happen_words.split(',') if w.strip()]
        return any(w in result for w in words)
