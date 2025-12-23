import json
import time
from typing import Optional
import loguru
import requests
from util.CookieManager import CookieManager
from util.IPv6ControllerClient import IPv6ControllerClient


class BiliRequest:
    def __init__(
        self,
        headers=None,
        cookies=None,
        cookies_config_path=None,
        proxy: str = "none",
        ipv6_controller_url: str = "",
    ):
        self.session = requests.Session()
        self.proxy_list = (
            [v.strip() for v in proxy.split(",") if len(v.strip()) != 0]
            if proxy
            else []
        )
        if len(self.proxy_list) == 0:
            raise ValueError("at least have none proxy")

        # 将 "none" 移动到列表末尾，实现优先使用代理，直连兜底
        if "none" in self.proxy_list:
            self.proxy_list.remove("none")
            self.proxy_list.append("none")

        self.now_proxy_idx = 0
        self._apply_proxy()  # 初始化时立即应用第一个代理
        self.cookieManager = CookieManager(cookies_config_path, cookies)
        self.headers = headers or {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,zh-TW;q=0.5,ja;q=0.4",
            "content-type": "application/x-www-form-urlencoded",
            "cookie": "",
            "referer": "https://show.bilibili.com/",
            "priority": "u=1, i",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        }
        self.request_count = 0  # 记录请求次数

        # IPv6 controller for automatic rotation on 412
        self.ipv6_controller: Optional[IPv6ControllerClient] = None
        if ipv6_controller_url:
            try:
                self.ipv6_controller = IPv6ControllerClient(ipv6_controller_url)
                loguru.logger.info(f"IPv6 Controller 已配置: {ipv6_controller_url}")
            except Exception as e:
                loguru.logger.warning(f"IPv6 Controller 初始化失败: {e}")

    def count_and_sleep(self, threshold=60, sleep_time=60):
        """
        当记录到一定次数就sleep
        """
        self.request_count += 1
        if self.request_count % threshold == 0:
            loguru.logger.info(f"达到 {threshold} 次请求 412，休眠 {sleep_time} 秒")
            time.sleep(sleep_time)

    def clear_request_count(self):
        self.request_count = 0

    def get(self, url, data=None, isJson=False):
        self.headers["cookie"] = self.cookieManager.get_cookies_str()
        if isJson:
            self.headers["Content-Type"] = "application/json"
            data = json.dumps(data)
        else:
            self.headers["Content-Type"] = "application/x-www-form-urlencoded"
        response = self.session.get(url, data=data, headers=self.headers, timeout=10)
        if response.status_code == 412:
            self.count_and_sleep()
            self._handle_412()
            return self.get(url, data, isJson)
        response.raise_for_status()
        self.clear_request_count()
        if response.json().get("msg", "") == "请先登录":
            raise RuntimeError("当前未登录，请重新登陆")
        return response

    def _apply_proxy(self):
        current_proxy = self.proxy_list[self.now_proxy_idx]
        if current_proxy == "none":
            self.session.proxies = {}  # 不使用任何代理，直连
        else:
            self.session.proxies = {
                "http": current_proxy,
                "https": current_proxy,
            }

    def switch_proxy(self):
        self.now_proxy_idx = (self.now_proxy_idx + 1) % len(self.proxy_list)
        self._apply_proxy()

    def _handle_412(self):
        """Handle 412 rate limiting error by rotating IPv6 or switching proxy."""
        if self.ipv6_controller:
            try:
                new_ip = self.ipv6_controller.rotate()
                loguru.logger.warning(f"412风控，轮换 IPv6 到 {new_ip}")
                return
            except Exception as e:
                loguru.logger.warning(f"IPv6 轮换失败 ({e})，回退到切换代理")
        # Fallback to proxy switching
        self.switch_proxy()
        loguru.logger.warning(
            f"412风控，切换代理到 {self.proxy_list[self.now_proxy_idx]}"
        )

    def post(self, url, data=None, isJson=False):
        self.headers["cookie"] = self.cookieManager.get_cookies_str()
        if isJson:
            self.headers["content-type"] = "application/json"
            data = json.dumps(data)
        else:
            self.headers["content-type"] = "application/x-www-form-urlencoded"
        response = self.session.post(url, data=data, headers=self.headers, timeout=10)
        if response.status_code == 412:
            self.count_and_sleep()
            self._handle_412()
            return self.post(url, data, isJson)
        response.raise_for_status()
        self.clear_request_count()
        if response.json().get("msg", "") == "请先登录":
            raise RuntimeError("当前未登录，请重新登陆")
        return response

    def get_request_name(self):
        try:
            if not self.cookieManager.have_cookies():
                loguru.logger.warning("获取用户名失败，请重新登录")
                return "未登录"
            result = self.get("https://api.bilibili.com/x/web-interface/nav").json()
            return result["data"]["uname"]
        except Exception:
            return "未登录"
