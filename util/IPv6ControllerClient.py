"""
IPv6 Controller Client for http-proxy-ipv6-pool

This module provides a client for the controller API of http-proxy-ipv6-pool,
allowing automatic IPv6 rotation when encountering 412 rate limiting errors.

API Reference:
- GET /ip      - Get current stable IPv6
- POST /rotate - Rotate to new random IPv6
- POST /set    - Set a specific IPv6 (must be within subnet)
"""

import requests
from urllib.parse import urlparse
from typing import Optional, Tuple


class IPv6ControllerClient:
    """Client for http-proxy-ipv6-pool controller API."""

    def __init__(self, controller_url: str, timeout: int = 5):
        """
        Initialize the controller client.

        Args:
            controller_url: Full URL with auth, e.g. http://admin:password@127.0.0.1:21992
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._parse_url(controller_url)

    def _parse_url(self, controller_url: str) -> None:
        """Parse URL and extract auth credentials."""
        parsed = urlparse(controller_url)

        self.username = parsed.username or ""
        self.password = parsed.password or ""

        # Reconstruct base URL without auth
        if parsed.port:
            self.base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        else:
            self.base_url = f"{parsed.scheme}://{parsed.hostname}"

        self.auth: Optional[Tuple[str, str]] = None
        if self.username or self.password:
            self.auth = (self.username, self.password)

    def get_current_ip(self) -> str:
        """
        Get current stable IPv6 address.

        Returns:
            Current IPv6 address string

        Raises:
            requests.RequestException: On network error
            ValueError: On invalid response
        """
        response = requests.get(
            f"{self.base_url}/ip", auth=self.auth, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get("ip", "")

    def rotate(self) -> str:
        """
        Rotate to a new random IPv6 address.

        Returns:
            New IPv6 address string

        Raises:
            requests.RequestException: On network error
            ValueError: On invalid response
        """
        response = requests.post(
            f"{self.base_url}/rotate", auth=self.auth, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get("ip", "")

    def set_ip(self, ip: str) -> str:
        """
        Set a specific IPv6 address (must be within subnet).

        Args:
            ip: IPv6 address to set

        Returns:
            Confirmed IPv6 address string

        Raises:
            requests.RequestException: On network error
            ValueError: On invalid response or IP not in subnet
        """
        response = requests.post(
            f"{self.base_url}/set",
            auth=self.auth,
            json={"ip": ip},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("ip", "")

    def test_connection(self) -> Tuple[bool, str]:
        """
        Test controller API connection.

        Returns:
            Tuple of (success, message)
        """
        try:
            current_ip = self.get_current_ip()
            return True, f"连接成功，当前 IPv6: {current_ip}"
        except requests.exceptions.Timeout:
            return False, f"连接超时 (>{self.timeout}s)"
        except requests.exceptions.ConnectionError:
            return False, "无法连接到控制器"
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return False, "认证失败，请检查用户名和密码"
            return False, f"HTTP 错误: {e.response.status_code}"
        except Exception as e:
            return False, f"未知错误: {str(e)}"


def test_ipv6_controller(
    controller_url: str, stable_proxy_url: str, timeout: int = 10
) -> str:
    """
    Test IPv6 controller functionality.

    This function:
    1. Tests controller API connectivity
    2. Gets current IPv6 from controller
    3. Uses stable proxy to request ipv6.ip.sb for actual exit IP
    4. Compares the two IPs

    Args:
        controller_url: Controller API URL, e.g. http://admin:password@127.0.0.1:21992
        stable_proxy_url: Stable proxy URL, e.g. http://admin:password@127.0.0.1:21991
        timeout: Request timeout in seconds

    Returns:
        Formatted test result string
    """
    output = []
    output.append("IPv6 Controller 测试结果:")
    output.append("=" * 50)

    # Test 1: Controller API connectivity
    output.append("\n📡 测试 Controller API 连接...")
    try:
        client = IPv6ControllerClient(controller_url, timeout=timeout)
        controller_ip = client.get_current_ip()
        output.append("✅ Controller API 连接成功")
        output.append(f"   当前配置的 IPv6: {controller_ip}")
    except Exception as e:
        output.append(f"❌ Controller API 连接失败: {e}")
        output.append("=" * 50)
        return "\n".join(output)

    # Test 2: Verify actual exit IP via stable proxy
    output.append("\n🌐 通过 Stable Proxy 验证实际出口 IP...")
    try:
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": stable_proxy_url, "https": stable_proxy_url}

        response = session.get("https://ipv6.ip.sb", timeout=timeout)
        actual_ip = response.text.strip()
        output.append("✅ Stable Proxy 连接成功")
        output.append(f"   实际出口 IPv6: {actual_ip}")

        # Compare IPs
        if controller_ip == actual_ip:
            output.append("\n✅ 两个 IP 一致，配置正确!")
        else:
            output.append("\n⚠️ IP 不一致:")
            output.append(f"   Controller 返回: {controller_ip}")
            output.append(f"   实际出口:       {actual_ip}")
    except Exception as e:
        output.append(f"❌ Stable Proxy 测试失败: {e}")

    output.append("\n" + "=" * 50)
    return "\n".join(output)


def rotate_and_verify(
    controller_url: str, stable_proxy_url: str, timeout: int = 10
) -> str:
    """
    Rotate IPv6 and verify the change.

    Args:
        controller_url: Controller API URL
        stable_proxy_url: Stable proxy URL
        timeout: Request timeout in seconds

    Returns:
        Formatted result string
    """
    output = []
    output.append("IPv6 轮换测试:")
    output.append("=" * 50)

    try:
        client = IPv6ControllerClient(controller_url, timeout=timeout)

        # Get current IP
        old_ip = client.get_current_ip()
        output.append(f"🔄 当前 IPv6: {old_ip}")

        # Rotate
        output.append("\n⏳ 正在轮换...")
        new_ip = client.rotate()
        output.append(f"✅ 新 IPv6: {new_ip}")

        if old_ip != new_ip:
            output.append("\n✅ 轮换成功，IP 已变化!")
        else:
            output.append("\n⚠️ IP 未变化 (可能已用尽地址池)")

        # Verify via stable proxy
        output.append("\n🌐 验证实际出口 IP...")
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": stable_proxy_url, "https": stable_proxy_url}

        response = session.get("https://ipv6.ip.sb", timeout=timeout)
        actual_ip = response.text.strip()
        output.append(f"   实际出口 IPv6: {actual_ip}")

        if new_ip == actual_ip:
            output.append("✅ 验证通过!")
        else:
            output.append("⚠️ 出口 IP 与 Controller 返回不一致")
    except Exception as e:
        output.append(f"❌ 轮换失败: {e}")

    output.append("\n" + "=" * 50)
    return "\n".join(output)
