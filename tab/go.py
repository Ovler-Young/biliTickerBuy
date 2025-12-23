import datetime
import os
import platform
import time
import gradio as gr
from gradio import SelectData
from loguru import logger
import requests

from task.buy import buy_new_terminal
from util import ConfigDB, Endpoint, GlobalStatusInstance, time_service


def withTimeString(string):
    return f"{datetime.datetime.now()}: {string}"


def go_tab(demo: gr.Blocks):
    with gr.Column():
        with gr.Column(elem_classes="rounded-xl border p-4  rounded-lg shadow-sm"):
            gr.Markdown("""
                ## 上传或填入你要抢票票种的配置信息
                """)
            with gr.Row():
                upload_ui = gr.Files(
                    label="上传多个配置文件,每一个上传的文件都会启动一个抢票程序",
                    file_count="multiple",
                )
                ticket_ui = gr.TextArea(
                    label="查看",
                    info="只能通过上传文件方式上传信息",
                    interactive=False,
                    visible=False,
                )
            with gr.Row(variant="compact"):
                gr.HTML(
                    """
                <div class="bg-red-50 border border-red-200 rounded-xl p-4 shadow-sm">
                    <p class="text-red-600 font-medium mb-2">
                        程序已经提前帮你校准时间，<strong>请设置成开票时间</strong>。切勿设置为开票前时间，
                        否则<strong>有封号风险</strong>！
                    </p>
                    <label for="datetime" class="block  font-semibold mb-1">选择抢票时间（精确到秒）</label>
                    <input 
                        type="datetime-local" 
                        id="datetime" 
                        name="datetime" 
                        step="1"
                        class="w-full border rounded-lg p-2 shadow-sm 
                            focus:outline-none focus:ring-2 focus:ring-blue-400 
                            hover:border-blue-400 transition-all"
                    >
                </div>
                """,
                    label="选择抢票的时间",
                )

        def upload(filepath):
            try:
                with open(filepath[0], "r", encoding="utf-8") as file:
                    content = file.read()
                return gr.update(content, visible=True)
            except Exception as e:
                return str(e)

        def file_select_handler(select_data: SelectData, files):
            file_label = files[select_data.index]
            try:
                with open(file_label, "r", encoding="utf-8") as file:
                    content = file.read()
                return content
            except Exception as e:
                return str(e)

        upload_ui.upload(fn=upload, inputs=upload_ui, outputs=ticket_ui)
        upload_ui.clear(
            fn=lambda x: gr.update("", visible=False),
            inputs=upload_ui,
            outputs=ticket_ui,
        )

        upload_ui.select(file_select_handler, upload_ui, ticket_ui)

        # 手动设置/更新时间偏差
        with gr.Accordion(label="手动设置/更新时间偏差", open=False):
            time_diff_ui = gr.Number(
                label="当前脚本时间偏差 (单位: ms)",
                info="你可以在这里手动输入时间偏差, 或点击下面按钮自动更新当前时间偏差。正值将推迟相应时间开始抢票, 负值将提前相应时间开始抢票。",
                value=float(format(time_service.get_timeoffset() * 1000, ".2f")),
            )  # type: ignore
            refresh_time_ui = gr.Button(value="点击自动更新时间偏差")
            refresh_time_ui.click(
                fn=lambda: format(
                    float(time_service.compute_timeoffset()) * 1000, ".2f"
                ),
                inputs=None,
                outputs=time_diff_ui,
            )
            time_diff_ui.change(
                fn=lambda x: time_service.set_timeoffset(
                    format(float(x) / 1000, ".5f")
                ),
                inputs=time_diff_ui,
                outputs=None,
            )

        with gr.Accordion(label="填写你的代理服务器[可选]", open=False):
            gr.Markdown("""
                        > **注意**：

                        填写代理服务器地址后，程序在使用这个配置文件后会在出现风控后后根据代理服务器去访问哔哩哔哩的抢票接口。

                        抢票前请确保代理服务器已经开启，并且可以正常访问哔哩哔哩的抢票接口。

                        支持 HTTP/HTTPS/SOCKS 代理。

                        """)

            def get_latest_proxy():
                return ConfigDB.get("https_proxy") or ""

            https_proxy_ui = gr.Textbox(
                label="填写抢票时候的代理服务器地址，使用逗号隔开|输入完成后，回车键保存",
                info="例如： http://127.0.0.1:8080,https://127.0.0.1:8081,socks5://127.0.0.1:1080",
                value=(ConfigDB.get("https_proxy") or ""),
            )

            def input_https_proxy(_https_proxy):
                ConfigDB.insert("https_proxy", _https_proxy)
                return gr.update(ConfigDB.get("https_proxy"))

            https_proxy_ui.submit(
                fn=input_https_proxy, inputs=https_proxy_ui, outputs=https_proxy_ui
            )

            test_proxy_btn = gr.Button("🔍 测试代理连通性")
            test_timeout_ui = gr.Number(
                label="测试代理超时时间(秒)",
                value=10,
                minimum=5,
                maximum=60,
                step=1,
            )

            test_result_ui = gr.Textbox(
                label="测试结果",
                lines=10,
                max_lines=15,
                interactive=False,
                placeholder="点击上方按钮开始测试代理连通性...",
            )

            def test_proxy_connectivity(proxy_string, timeout):
                """测试代理连通性"""
                try:
                    from util.ProxyTester import test_proxy_connectivity

                    if not proxy_string or proxy_string.strip() == "":
                        proxy_string = "none"  # 测试直连
                    result = test_proxy_connectivity(proxy_string, int(timeout))
                    return result
                except Exception as e:
                    return f"❌ 测试过程中发生错误: {str(e)}"

            test_proxy_btn.click(
                fn=test_proxy_connectivity,
                inputs=[https_proxy_ui, test_timeout_ui],
                outputs=test_result_ui,
            )

            # IPv6 Controller configuration
            gr.Markdown(
                """
                ---
                ### 🔄 IPv6 轮换控制器 (http-proxy-ipv6-pool)

                如果你使用 [http-proxy-ipv6-pool](https://github.com/example/http-proxy-ipv6-pool) 服务，
                可以配置控制器 API，在遇到 412 风控时自动轮换 IPv6 地址。
                """
            )

            ipv6_controller_url_ui = gr.Textbox(
                label="IPv6 Controller API 地址｜输入完成后，回车键保存",
                info="例如: http://admin:password@127.0.0.1:21992",
                value=(ConfigDB.get("ipv6_controller_url") or ""),
            )

            ipv6_stable_proxy_ui = gr.Textbox(
                label="IPv6 Stable Proxy 地址｜输入完成后，回车键保存",
                info="例如: http://admin:password@127.0.0.1:21991",
                value=(ConfigDB.get("ipv6_stable_proxy") or ""),
            )

            def input_ipv6_controller_url(_url):
                ConfigDB.insert("ipv6_controller_url", _url)
                return gr.update(value=ConfigDB.get("ipv6_controller_url"))

            def input_ipv6_stable_proxy(_url):
                ConfigDB.insert("ipv6_stable_proxy", _url)
                return gr.update(value=ConfigDB.get("ipv6_stable_proxy"))

            ipv6_controller_url_ui.submit(
                fn=input_ipv6_controller_url,
                inputs=ipv6_controller_url_ui,
                outputs=ipv6_controller_url_ui,
            )

            ipv6_stable_proxy_ui.submit(
                fn=input_ipv6_stable_proxy,
                inputs=ipv6_stable_proxy_ui,
                outputs=ipv6_stable_proxy_ui,
            )

            with gr.Row():
                test_ipv6_btn = gr.Button("🔍 测试 IPv6 Controller 连接")
                rotate_ipv6_btn = gr.Button("🔄 手动轮换 IPv6")

            ipv6_test_result_ui = gr.Textbox(
                label="IPv6 测试结果",
                lines=12,
                max_lines=20,
                interactive=False,
                placeholder="点击上方按钮开始测试 IPv6 Controller...",
            )

            def test_ipv6_controller_fn(controller_url, stable_proxy_url, timeout):
                """Test IPv6 controller connectivity"""
                try:
                    from util.IPv6ControllerClient import test_ipv6_controller

                    if not controller_url or controller_url.strip() == "":
                        return "❌ 请先填写 IPv6 Controller API 地址"
                    if not stable_proxy_url or stable_proxy_url.strip() == "":
                        return "❌ 请先填写 IPv6 Stable Proxy 地址"
                    return test_ipv6_controller(
                        controller_url, stable_proxy_url, int(timeout)
                    )
                except Exception as e:
                    return f"❌ 测试过程中发生错误: {str(e)}"

            def rotate_ipv6_fn(controller_url, stable_proxy_url, timeout):
                """Rotate IPv6 and verify"""
                try:
                    from util.IPv6ControllerClient import rotate_and_verify

                    if not controller_url or controller_url.strip() == "":
                        return "❌ 请先填写 IPv6 Controller API 地址"
                    if not stable_proxy_url or stable_proxy_url.strip() == "":
                        return "❌ 请先填写 IPv6 Stable Proxy 地址"
                    return rotate_and_verify(
                        controller_url, stable_proxy_url, int(timeout)
                    )
                except Exception as e:
                    return f"❌ 轮换过程中发生错误: {str(e)}"

            test_ipv6_btn.click(
                fn=test_ipv6_controller_fn,
                inputs=[ipv6_controller_url_ui, ipv6_stable_proxy_ui, test_timeout_ui],
                outputs=ipv6_test_result_ui,
            )

            rotate_ipv6_btn.click(
                fn=rotate_ipv6_fn,
                inputs=[ipv6_controller_url_ui, ipv6_stable_proxy_ui, test_timeout_ui],
                outputs=ipv6_test_result_ui,
            )

        with gr.Accordion(label="配置抢票成功后播放音乐[可选]", open=False):
            with gr.Row():
                audio_path_ui = gr.Audio(
                    label="上传提示声音[只支持格式wav]",
                    type="filepath",
                    loop=True,
                    value=(ConfigDB.get("audioPath") or None),
                )
        with gr.Accordion(label="配置抢票推送消息[可选]", open=False):
            gr.Markdown(
                """
                🗨️ **抢票成功提醒**
    
                > 你需要去对应的网站获取 key 或 token，然后填入下面的输入框  
                > [Server酱<sup>Turbo</sup>](https://sct.ftqq.com/sendkey) | [pushplus](https://www.pushplus.plus/uc.html) | [Server酱<sup>3</sup>](https://sc3.ft07.com/sendkey) | [ntfy](https://ntfy.sh/) | [Bark](https://bark.day.app/)  
                > 留空以不启用提醒功能
    
                ### 🔍 推送服务对比
    
                | 服务     | 优点                               | 缺点                            |
                |----------|------------------------------------|---------------------------------|
                | Server酱<sup>Turbo</sup> | 简单易用，微信推送              | 微信推送很难看到 |
                | pushplus | 简单易用，微信推送| 微信推送很难看到               |
                | Server酱<sup>3</sup> | APP推送，有中文文档              | 配置复杂 |
                | ntfy     | APP推送, 功能强大, 支持长期响铃 | 配置复杂，需要手动搭建或注册公网地址 |
                | Bark     | iOS通知推送，配置简单，无视静音和勿扰模式，支持APP跳转 | 仅支持iOS设备 |
    
                ✅ 推荐：初次使用建议选择 **pushplus** 或 **Server酱ᵀᵘʳᵇᵒ**，配置最简单  
                🍎 iOS用户推荐使用 **Bark**，通知效果最佳  
                🛠️ 追求高度自由/有自建服务器/需要在抢票成功时通过手机播放铃声时，建议用 **ntfy** 或 **Server酱³**
                """
            )
            with gr.Row():
                serverchan_ui = gr.Textbox(
                    value=(ConfigDB.get("serverchanKey") or ""),
                    label="Server酱ᵀᵘʳᵇᵒ的SendKey｜输入完成后，回车键保存",
                    interactive=True,
                    info="https://sct.ftqq.com/",
                )

                serverchan3_ui = gr.Textbox(
                    value=(ConfigDB.get("serverchan3ApiUrl") or ""),
                    label="Server酱³的API URL｜输入完成后，回车键保存",
                    interactive=True,
                    info="https://sc3.ft07.com/",
                )

                pushplus_ui = gr.Textbox(
                    value=(ConfigDB.get("pushplusToken") or ""),
                    label="PushPlus的Token｜输入完成后，回车键保存",
                    interactive=True,
                    info="https://www.pushplus.plus/",
                )

                bark_ui = gr.Textbox(
                    value=(ConfigDB.get("barkToken") or ""),
                    label="Bark的Token｜输入完成后，回车键保存",
                    interactive=True,
                    info='iOS Bark App的"服务器"页面获取，例如: jmGYK*****(并非Device Token)；自托管服务请输入完整推送地址，例如: https://bark.example.app/jmGYK*****',
                )

            with gr.Accordion(label="Ntfy配置", open=False):
                ntfy_ui = gr.Textbox(
                    value=(ConfigDB.get("ntfyUrl") or ""),
                    label="Ntfy服务器URL｜输入完成后，回车键保存",
                    interactive=True,
                    info="例如: https://ntfy.sh/your-topic",
                )

                with gr.Accordion(label="Ntfy认证配置[可选]", open=False):
                    with gr.Row():
                        ntfy_username_ui = gr.Textbox(
                            value=(ConfigDB.get("ntfyUsername") or ""),
                            label="Ntfy用户名",
                            interactive=True,
                            info="如果你的Ntfy服务器需要认证",
                        )

                        ntfy_password_ui = gr.Textbox(
                            value=(ConfigDB.get("ntfyPassword") or ""),
                            label="Ntfy密码",
                            interactive=True,
                            type="password",
                        )

                    def test_ntfy_connection():
                        url = ConfigDB.get("ntfyUrl")
                        username = ConfigDB.get("ntfyUsername")
                        password = ConfigDB.get("ntfyPassword")

                        if not url:
                            return "错误: 请先设置Ntfy服务器URL"

                        from util import NtfyUtil

                        success, message = NtfyUtil.test_connection(
                            url, username, password
                        )

                        if success:
                            return f"成功: {message}"
                        else:
                            return f"错误: {message}"

                    test_ntfy_button = gr.Button("测试Ntfy连接")
                    test_ntfy_result = gr.Textbox(label="测试结果", interactive=False)
                    test_ntfy_button.click(
                        fn=test_ntfy_connection, inputs=[], outputs=test_ntfy_result
                    )

            # 推送测试按钮区域
            with gr.Column():
                test_all_push_button = gr.Button("🧪 测试所有推送")
                test_push_result = gr.Textbox(label="推送测试结果", interactive=False)

            def inner_input_serverchan(x):
                ConfigDB.insert("serverchanKey", x)
                return gr.update(value=ConfigDB.get("serverchanKey"))

            def inner_input_serverchan3(x):
                ConfigDB.insert("serverchan3ApiUrl", x)
                return gr.update(value=ConfigDB.get("serverchan3ApiUrl"))

            def inner_input_pushplus(x):
                ConfigDB.insert("pushplusToken", x)
                return gr.update(value=ConfigDB.get("pushplusToken"))

            def inner_input_bark(x):
                ConfigDB.insert("barkToken", x)
                return gr.update(value=ConfigDB.get("barkToken"))

            def inner_input_ntfy(x):
                ConfigDB.insert("ntfyUrl", x)
                return gr.update(value=ConfigDB.get("ntfyUrl"))

            def inner_input_ntfy_username(x):
                ConfigDB.insert("ntfyUsername", x)
                return gr.update(value=ConfigDB.get("ntfyUsername"))

            def inner_input_ntfy_password(x):
                ConfigDB.insert("ntfyPassword", x)
                return gr.update(value=ConfigDB.get("ntfyPassword"))

            def inner_input_audio_path(x):
                ConfigDB.insert("audioPath", x)
                return gr.update(value=ConfigDB.get("audioPath"))

            def test_all_push():
                """调用NotifierManager统一测试所有推送渠道"""
                try:
                    from util.Notifier import NotifierManager

                    return NotifierManager.test_all_notifiers()
                except Exception as e:
                    logger.exception(e)
                    return f"错误: 测试过程中发生异常 - {str(e)}"

            serverchan_ui.submit(
                fn=inner_input_serverchan, inputs=serverchan_ui, outputs=serverchan_ui
            )

            serverchan3_ui.submit(
                fn=inner_input_serverchan3,
                inputs=serverchan3_ui,
                outputs=serverchan3_ui,
            )

            pushplus_ui.submit(
                fn=inner_input_pushplus, inputs=pushplus_ui, outputs=pushplus_ui
            )

            bark_ui.submit(fn=inner_input_bark, inputs=bark_ui, outputs=bark_ui)

            ntfy_ui.submit(fn=inner_input_ntfy, inputs=ntfy_ui, outputs=ntfy_ui)

            ntfy_username_ui.submit(
                fn=inner_input_ntfy_username,
                inputs=ntfy_username_ui,
                outputs=ntfy_username_ui,
            )

            ntfy_password_ui.submit(
                fn=inner_input_ntfy_password,
                inputs=ntfy_password_ui,
                outputs=ntfy_password_ui,
            )

            test_all_push_button.click(
                fn=test_all_push, inputs=[], outputs=test_push_result
            )

            audio_path_ui.upload(
                fn=inner_input_audio_path, inputs=audio_path_ui, outputs=audio_path_ui
            )
        with gr.Accordion(label="杂项配置", open=False):
            show_random_message_ui = gr.Checkbox(
                label="关闭群友语录",
                value=True,
                info="关闭后，抢票失败时将不再显示有趣的语录",
            )

        with gr.Row():
            interval_ui = gr.Number(
                label="抢票间隔",
                value=1000,
                minimum=1,
                info="设置抢票任务之间的时间间隔（单位：毫秒），建议不要设置太小",
            )
            choices = ["网页"]
            if platform.system() == "Windows":
                choices.insert(0, "终端")  # 或 append，取决于你想要顺序
            terminal_ui = gr.Radio(
                label="日志显示方式",
                choices=choices,
                value=choices[0],
                info="日志显示的方式,非windows用戶只支持網頁",
                type="value",
                interactive=True,
            )

    def try_assign_endpoint(endpoint_url, payload):
        try:
            response = requests.post(f"{endpoint_url}/buy", json=payload, timeout=5)
            if response.status_code == 200:
                return True
            elif response.status_code == 409:
                logger.info(f"{endpoint_url} 已经占用")
                return False
            else:
                return False

        except Exception as e:
            logger.exception(e)
            raise e

    def split_proxies(https_proxy_list: list[str], task_num: int) -> list[list[str]]:
        assigned_proxies: list[list[str]] = [[] for _ in range(task_num)]
        for i, proxy in enumerate(https_proxy_list):
            assigned_proxies[i % task_num].append(proxy)
        return assigned_proxies

    def start_go(
        files,
        time_start,
        interval,
        audio_path,
        https_proxys,
        ipv6_controller_url,
        terminal_ui,
        hide_random_message,
    ):
        if not files:
            return [gr.update(value=withTimeString("未提交抢票配置"), visible=True)]
        yield [
            gr.update(value=withTimeString("开始多开抢票,详细查看终端"), visible=True)
        ]
        endpoints = GlobalStatusInstance.available_endpoints()
        endpoints_next_idx = 0
        https_proxy_list = ["none"] + https_proxys.split(",")
        assigned_proxies: list[list[str]] = []
        assigned_proxies_next_idx = 0
        for idx, filename in enumerate(files):
            with open(filename, "r", encoding="utf-8") as file:
                content = file.read()
            filename_only = os.path.basename(filename)
            logger.info(f"启动 {filename_only}")
            # 先分配worker
            while endpoints_next_idx < len(endpoints) and terminal_ui == "网页":
                success = try_assign_endpoint(
                    endpoints[endpoints_next_idx].endpoint,
                    payload={
                        "force": True,
                        "train_info": content,
                        "time_start": time_start,
                        "interval": interval,
                        "audio_path": audio_path,
                        "pushplusToken": ConfigDB.get("pushplusToken"),
                        "serverchanKey": ConfigDB.get("serverchanKey"),
                        "serverchan3ApiUrl": ConfigDB.get("serverchan3ApiUrl"),
                        "barkToken": ConfigDB.get("barkToken"),
                        "ntfy_url": ConfigDB.get("ntfyUrl"),
                        "ntfy_username": ConfigDB.get("ntfyUsername"),
                        "ntfy_password": ConfigDB.get("ntfyPassword"),
                    },
                )
                endpoints_next_idx += 1
                if success:
                    break
            else:
                # 再分配https_proxys
                if assigned_proxies == []:
                    left_task_num = len(files) - idx
                    assigned_proxies = split_proxies(https_proxy_list, left_task_num)

                buy_new_terminal(
                    endpoint_url=demo.local_url,
                    tickets_info=content,
                    time_start=time_start,
                    interval=interval,
                    audio_path=audio_path,
                    pushplusToken=ConfigDB.get("pushplusToken"),
                    serverchanKey=ConfigDB.get("serverchanKey"),
                    serverchan3ApiUrl=ConfigDB.get("serverchan3ApiUrl"),
                    barkToken=ConfigDB.get("barkToken"),
                    ntfy_url=ConfigDB.get("ntfyUrl"),
                    ntfy_username=ConfigDB.get("ntfyUsername"),
                    ntfy_password=ConfigDB.get("ntfyPassword"),
                    https_proxys=",".join(assigned_proxies[assigned_proxies_next_idx]),
                    ipv6_controller_url=ipv6_controller_url,
                    terminal_ui=terminal_ui,
                    show_random_message=not hide_random_message,
                )
                assigned_proxies_next_idx += 1
        gr.Info("正在启动，请等待抢票页面弹出。")

    go_btn = gr.Button("开始抢票")

    _time_tmp = gr.Textbox(visible=False)
    go_btn.click(
        fn=None,
        inputs=None,
        outputs=_time_tmp,
        js='(x) => document.getElementById("datetime").value',
    )
    _report_tmp = gr.Button(visible=False)
    _report_tmp.api_info

    # hander endpoint hearts

    _end_point_tinput = gr.Textbox(visible=False)

    def report(end_point, detail):
        now = time.time()
        GlobalStatusInstance.endpoint_details[end_point] = Endpoint(
            endpoint=end_point, detail=detail, update_at=now
        )

    _report_tmp.click(
        fn=report,
        inputs=[_end_point_tinput, _time_tmp],  # fake useage
        api_name="report",
    )

    def tick():
        return f"当前时间戳：{int(time.time())}"

    timer = gr.Textbox(label="定时更新", interactive=False, visible=False)
    demo.load(fn=tick, inputs=None, outputs=timer, every=1)

    @gr.render(inputs=timer)
    def show_split(text):
        endpoints = GlobalStatusInstance.available_endpoints()
        if len(endpoints) != 0:
            gr.Markdown("## 当前运行终端列表")
            for endpoint in endpoints:
                with gr.Row():
                    gr.Button(
                        value=f"点击跳转 🚀 {endpoint.endpoint} {endpoint.detail}",
                        link=endpoint.endpoint,
                    )

    go_btn.click(
        fn=start_go,
        inputs=[
            upload_ui,
            _time_tmp,
            interval_ui,
            audio_path_ui,
            https_proxy_ui,
            ipv6_controller_url_ui,
            terminal_ui,
            show_random_message_ui,
        ],
    )
