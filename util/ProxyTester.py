import re
import time
import requests
import loguru
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
# 代理连通性测试工具
class ProxyTester:
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
    
    # 测试单个代理连通性
    def test_single_proxy(self, proxy: str) -> Dict[str, Any]:
        result = {
            "proxy": proxy,
            "status": "failed",
            "response_time": None,
            "error": None,
            "ip_info": None
        }
        
        try:
            session = requests.Session()
            session.trust_env = False
            # 配置代理
            if proxy == "none" or proxy.lower() == "direct":
                session.proxies = {}
                result["proxy"] = "直连"
            else:
                if not self._validate_proxy_format(proxy):
                    result["error"] = "代理格式无效"
                    return result
                    
                session.proxies = {
                    "http": proxy,
                    "https": proxy
                }
            
            # 测试连通性和响应时间
            start_time = time.time()
            response = session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                timeout=self.timeout,
                headers={
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
                }
            )
            end_time = time.time()
            response_time = round((end_time - start_time) * 1000, 2)  # 毫秒
            
            if response.status_code == 200:
                result["status"] = "success"
                result["response_time"] = response_time
                # 获取出口IP信息
                result["ip_info"] = self._get_ip_info(session)
            else:
                result["error"] = f"B站连接失败: HTTP {response.status_code}"
                result["status"] = "partial"
                result["response_time"] = response_time
                # 部分成功时也尝试获取IP
                result["ip_info"] = self._get_ip_info(session)
        except requests.exceptions.Timeout:
            result["error"] = f"连接超时 (>{self.timeout}s)"
        except requests.exceptions.ProxyError:
            result["error"] = "代理服务器错误或无法连接"
        except requests.exceptions.ConnectionError as e:
            if "proxy" in str(e).lower():
                result["error"] = "代理连接失败"
            else:
                result["error"] = "网络连接失败"
        except Exception as e:
            result["error"] = f"未知错误: {str(e)}"
        
        return result
    
    def _get_ip_info(self, session) -> str:
        """获取出口IP信息"""
        # 服务列表：优先详细信息，然后降级到基础服务
        ip_services = [
            {
                'name': 'ip-api.com',
                'url': 'http://ip-api.com/json/',
                'parser': lambda data: f"{data.get('query', '未知')} ({data.get('city', '未知')}, {data.get('isp', '未知')})"
            },
            {
                'name': 'httpbin.org', 
                'url': 'http://httpbin.org/ip',
                'parser': lambda data: data.get('origin', '未知')
            }
        ]
        
        for service in ip_services:
            try:
                ip_response = session.get(service['url'], timeout=3)
                if ip_response.status_code == 200:
                    ip_data = ip_response.json()
                    return service['parser'](ip_data)
            except Exception:
                continue
        
        return "IP获取失败"
    
    # 验证代理格式是否正确
    def _validate_proxy_format(self, proxy: str) -> bool:
        try:
            # 基本格式检查
            if not proxy or proxy.strip() == "":
                return False
            
            # 检查是否包含协议
            if not any(proxy.startswith(protocol) for protocol in ["http://", "https://", "socks5://", "socks4://"]):
                return False
            
            # 检查是否包含端口
            if ":" not in proxy.split("://")[1]:
                return False
                
            return True
        except:
            return False
    # 测试代理列表的连通性
    def test_proxy_list(self, proxy_string: str, max_workers: int = 5) -> List[Dict[str, Any]]:
        if not proxy_string or proxy_string.strip() == "":
            proxy_list = ["none"]
        else:
            proxy_list = [p.strip() for p in proxy_string.split(",") if p.strip()]
            if not proxy_list:
                proxy_list = ["none"]
            else:
                if "none" not in [p.lower() for p in proxy_list] and "direct" not in [p.lower() for p in proxy_list]:
                    proxy_list.insert(0, "none")
        
        results = []
        # 使用线程池并发测试
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {
                executor.submit(self.test_single_proxy, proxy): proxy 
                for proxy in proxy_list
            }
            
            for future in as_completed(future_to_proxy):
                try:
                    result = future.result()
                    results.append(result)
                    loguru.logger.info(f"代理测试完成: {result['proxy']} - {result['status']}")
                except Exception as e:
                    loguru.logger.error(f"代理测试异常: {e}")
        # 按照原始顺序排序结果（直连在前，然后是代理）
        def get_sort_key(result):
            proxy = result['proxy']
            if proxy == "直连" or proxy.lower() in ["none", "direct"]:
                return (0, proxy)  
            else:
                try:
                    return (1, proxy_list.index(proxy))
                except ValueError:
                    return (2, proxy)
        results.sort(key=get_sort_key)
        return results
    
    def test_rotation(self, proxy: str, num_requests: int = 3) -> Dict[str, Any]:
        """
        测试代理的 Keep-Alive 和 IP 旋转行为。
        分两轮测试：
          1. 同一 Session 多次请求（验证 Keep-Alive 是否保持同一 IP）
          2. 每次请求重建 Session（验证断开连接后代理是否分配新 IP）
        """
        result = {
            "proxy": proxy,
            "keep_alive_ips": [],
            "rotation_ips": [],
            "keep_alive_same": None,
            "rotation_changed": None,
            "error": None
        }

        if proxy == "none" or proxy.lower() == "direct":
            result["error"] = "直连模式无需测试旋转"
            return result

        if not self._validate_proxy_format(proxy):
            result["error"] = "代理格式无效"
            return result

        # 第一轮：Keep-Alive 测试（同一 Session）
        try:
            session = requests.Session()
            session.trust_env = False
            session.proxies = {"http": proxy, "https": proxy}
            for _ in range(num_requests):
                ip = self._get_ip_only(session)
                if ip:
                    result["keep_alive_ips"].append(ip)
            session.close()
        except Exception as e:
            result["error"] = f"Keep-Alive 测试失败: {e}"
            return result

        # 第二轮：IP 旋转测试（每次重建 Session）
        try:
            for _ in range(num_requests):
                session = requests.Session()
                session.trust_env = False
                session.proxies = {"http": proxy, "https": proxy}
                ip = self._get_ip_only(session)
                if ip:
                    result["rotation_ips"].append(ip)
                session.close()
        except Exception as e:
            result["error"] = f"IP 旋转测试失败: {e}"
            return result

        # 分析结果
        if len(result["keep_alive_ips"]) > 1:
            result["keep_alive_same"] = len(set(result["keep_alive_ips"])) == 1
        if len(result["rotation_ips"]) > 1:
            result["rotation_changed"] = len(set(result["rotation_ips"])) > 1

        return result

    def _get_ip_only(self, session) -> str:
        """仅获取 IP 地址，不包含地理信息"""
        try:
            response = session.get("http://httpbin.org/ip", timeout=5)
            if response.status_code == 200:
                return response.json().get("origin", "")
        except Exception:
            pass
        return ""

    # 格式化测试结果为可读文本
    def format_test_results(self, results: List[Dict[str, Any]], rotation_result: Dict[str, Any] = None) -> str:
        output = []
        output.append("代理连通性测试结果:")
        output.append("=" * 50)
        
        success_count = 0
        for i, result in enumerate(results, 1):
            proxy = result["proxy"]
            status = result["status"]
            response_time = result["response_time"]
            error = result["error"]
            ip_info = result["ip_info"]
            
            if status == "success":
                output.append(f"✅ [{i}] {proxy}")
                output.append(f"    响应时间: {response_time}ms")
                if ip_info and ip_info != "IP获取失败":
                    output.append(f"    出口IP: {ip_info}")
                success_count += 1
            elif status == "partial":
                output.append(f"⚠️  [{i}] {proxy}")
                output.append(f"    响应时间: {response_time}ms")
                if ip_info and ip_info != "IP获取失败":
                    output.append(f"    出口IP: {ip_info}")
                output.append(f"    警告: {error}")
            else:
                output.append(f"❌ [{i}] {proxy}")
                output.append(f"    错误: {error}")
            
            output.append("")
        
        output.append("=" * 50)
        output.append(f"测试统计: {success_count}/{len(results)} 个代理可用")

        # 显示旋转测试结果
        if rotation_result:
            output.append("")
            output.append("=" * 50)
            output.append("IP 旋转测试结果:")
            if rotation_result.get("error"):
                output.append(f"  ⚠️ {rotation_result['error']}")
            else:
                # Keep-Alive 结果
                ka_ips = rotation_result.get("keep_alive_ips", [])
                if ka_ips:
                    output.append(f"  Keep-Alive ({len(ka_ips)}次请求，同一Session): {', '.join(ka_ips)}")
                    if rotation_result.get("keep_alive_same"):
                        output.append("    ✅ IP保持不变，长连接生效")
                    elif rotation_result.get("keep_alive_same") is False:
                        output.append("    ⚠️ IP发生变化，长连接可能未生效")
                # Rotation 结果
                rot_ips = rotation_result.get("rotation_ips", [])
                if rot_ips:
                    output.append(f"  断开重连 ({len(rot_ips)}次请求，每次新Session): {', '.join(rot_ips)}")
                    if rotation_result.get("rotation_changed"):
                        output.append("    ✅ IP发生变化，代理池旋转生效")
                    elif rotation_result.get("rotation_changed") is False:
                        output.append("    ⚠️ IP未变化，代理池可能未旋转")

        return "\n".join(output)


def test_proxy_connectivity(proxy_string: str = "none", timeout: int = 10) -> str:
    tester = ProxyTester(timeout=timeout)
    results = tester.test_proxy_list(proxy_string)

    # 对第一个非直连的代理执行旋转测试
    rotation_result = None
    for r in results:
        proxy = r.get("proxy", "")
        if proxy not in ["直连", "none", "direct"] and r.get("status") == "success":
            rotation_result = tester.test_rotation(proxy)
            break

    return tester.format_test_results(results, rotation_result)

