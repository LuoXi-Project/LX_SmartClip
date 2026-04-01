from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from os import urandom
import json
from time import time
from datetime import datetime, timedelta
import traceback
import base64
import logging
import requests
from urllib.parse import urljoin
from requests.exceptions import RequestException, Timeout
import locale
import subprocess

logger = logging.getLogger(__name__)


def decrypt_data(key: str, encrypted_data: str) -> dict:
    """Decrypt data with AES-GCM using the provided encrypted data which includes IV and tag."""
    try:
        # base64解码key
        key = base64.b64decode(key)
        encrypted_data = base64.b64decode(encrypted_data)

        iv = encrypted_data[:12]  # Extract IV from the beginning
        tag = encrypted_data[-16:]  # Extract tag from the end
        ciphertext = encrypted_data[12:-16]  # Extract ciphertext
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Decode the JSON string back into a dictionary
        return json.loads(plaintext.decode('utf-8'))
    except Exception as e:
        # logger.error(traceback.format_exc())
        logger.error(f"[密钥验证] 密钥有误，请检查密钥是否正确")
        return None 

def get_mac_address():
    import platform
    import os
    import re
    import locale
    import subprocess

    system = platform.system()

    if system == "Windows":
        try:
            # 使用subprocess替代os.popen，使用二进制模式
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process = subprocess.Popen(
                "getmac /v /fo list",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                shell=True,
                encoding=None  # 使用二进制模式
            )
            output_bytes, _ = process.communicate()
            
            # 尝试不同的编码方式解码
            encodings = ['gbk', 'utf-8', 'cp936', 'ascii']
            output = None
            for encoding in encodings:
                try:
                    output = output_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if output is None:
                # 如果所有编码都失败，尝试忽略错误
                output = output_bytes.decode('gbk', errors='ignore')
            
            # 处理输出
            macs = re.findall(r"([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})", output)
            valid_macs = [mac for mac in macs if mac.lower() != "暂缺"]
            if valid_macs:
                return valid_macs[0]
            
            # 如果getmac命令失败，尝试使用wmic
            process = subprocess.Popen(
                "wmic nic where PhysicalAdapter=True get MACAddress",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                shell=True,
                encoding=None  # 使用二进制模式
            )
            output_bytes, _ = process.communicate()
            
            # 尝试解码
            for encoding in encodings:
                try:
                    output = output_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
                    
            if output is None:
                output = output_bytes.decode('gbk', errors='ignore')
                
            macs = re.findall(r"([0-9A-Fa-f]{2}(?:[:][0-9A-Fa-f]{2}){5})", output)
            return macs[0] if macs else None
            
        except Exception as e:
            logger.error(f"获取MAC地址时出错: {str(e)}")
            return None

    elif system == "Linux":
        try:
            process = subprocess.Popen(
                "ifconfig",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                encoding=None  # 使用二进制模式
            )
            output_bytes, _ = process.communicate()
            try:
                output = output_bytes.decode('utf-8')
            except UnicodeDecodeError:
                output = output_bytes.decode('utf-8', errors='ignore')
                
            macs = re.findall(r"ether ([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})", output)
            return macs[0][0] if macs else None
        except Exception as e:
            logger.error(f"Linux获取MAC地址时出错: {str(e)}")
            return None

    elif system == "Darwin":  # macOS
        try:
            process = subprocess.Popen(
                "ifconfig",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                encoding=None  # 使用二进制模式
            )
            output_bytes, _ = process.communicate()
            try:
                output = output_bytes.decode('utf-8')
            except UnicodeDecodeError:
                output = output_bytes.decode('utf-8', errors='ignore')
                
            macs = re.findall(r"ether ([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5})", output)
            return macs[0][0] if macs else None
        except Exception as e:
            logger.error(f"macOS获取MAC地址时出错: {str(e)}")
            return None

    return None

# 读取配置文件（源码运行：与 secret.py 同目录；打包运行：优先 exe 同目录）
def get_config():
    import os
    import sys

    candidates: list[str] = []

    # PyInstaller/冻结环境：允许用户在 exe 同目录放置可编辑 config.json
    if getattr(sys, "frozen", False):
        try:
            exe_dir = os.path.abspath(os.path.dirname(sys.executable))
            candidates.append(os.path.join(exe_dir, "config.json"))
        except Exception:
            pass

    # 源码运行/兜底：与 secret.py 同目录（避免受进程 cwd 影响）
    candidates.append(os.path.join(os.path.abspath(os.path.dirname(__file__)), "config.json"))

    for config_file in candidates:
        try:
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except PermissionError as e:
            logger.error("读取 config.json 失败（权限不足）: %s (%s)", config_file, e)
        except Exception as e:
            logger.error("读取 config.json 失败: %s (%s)", config_file, e)

    return {}


def _card_server_settings(local_config):
    """返回 (api_base, timeout_sec)，无效时 (None, None)。"""
    srv = local_config.get("卡密服务器") or {}
    api = (srv.get("API地址") or "").strip()
    try:
        timeout = int(srv.get("请求超时", 30))
    except (TypeError, ValueError):
        timeout = 30
    if not api:
        return None, None
    return api, timeout

def card_login(card):
    try:
        local_config = get_config()
        api_base, req_timeout = _card_server_settings(local_config)
        if not api_base:
            logger.error("未配置卡密服务器：请在 backend/config.json 中配置 卡密服务器.API地址")
            return None

        mac = get_mac_address()
        if not mac:
            logger.error("无法获取MAC地址！无法登录！")
            return None

        url = urljoin(api_base, "/card/card_login")
        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "type": "智剪",
            "card": card.strip(),  # 去除可能的空白字符
            "mac": mac
        }

        # 设置requests的编码处理
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=req_timeout,
        )
        response.encoding = 'utf-8'  # 强制使用UTF-8编码
        
        if response.status_code == 200:
            try:
                resp_json = response.json()
                if resp_json.get("code") == 0:
                    key = resp_json["data"]["key"]
                    data = resp_json["data"]["data"]
                    msg = resp_json["data"]["msg"]

                    data_json = decrypt_data(key, data)
                    if data_json:
                        if "type" in data_json:
                            if data_json["success"] and data_json["type"] == "智剪":
                                time_difference = abs(datetime.now() - datetime.fromtimestamp(data_json["ts"]))
                                in_area = time_difference <= timedelta(seconds=int(data_json["timeout"]))
                                if in_area:
                                    logger.info(f"[密钥验证] 登录成功: {msg}")
                                    return resp_json
                                else:
                                    logger.error(f"[密钥验证] 错误: {msg}")
                                    return None
                            else:
                                logger.error(f"[密钥验证] 错误: {msg}")
                                return None
                        else:
                            return card_login(card)
                else:
                    error_msg = resp_json.get('detail', '未知错误')
                    logger.error(f"[密钥验证] 错误: {error_msg}")
                    return None
            except json.JSONDecodeError as je:
                logger.error(f"[密钥验证] JSON解析错误: {str(je)}")
                return None
        else:
            try:
                resp_json = response.json()
                error_msg = resp_json.get('detail', '未知错误')
            except:
                error_msg = response.text
            logger.error(f"[密钥验证] 错误码: {response.status_code}, {error_msg}")
            return None

    except RequestException as e:
        logger.error(f"[密钥验证] 请求过程中发生错误: {str(e)}")
        return None
    except Timeout:
        logger.error("[密钥验证] 请求超时，请稍后重试。")
        return None
    except Exception as e:
        logger.error(f"[密钥验证] 发生未知错误: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def card_unbind(card):
    try:
        local_config = get_config()
        api_base, req_timeout = _card_server_settings(local_config)
        if not api_base:
            logger.error("未配置卡密服务器，无法解绑")
            return {"code": -1, "success": False, "data": {"msg": "未配置卡密服务器"}}

        mac = get_mac_address()
        if not mac:
            logger.error("无法获取MAC地址！无法解绑！")
            return {"ret": -1, "msg": "无法获取MAC地址"}

        url = urljoin(api_base, "/card/unbind_card")
        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "type": "智剪",
            "card": card.strip(),  # 去除可能的空白字符
            "mac": mac
        }

        # 设置requests的编码处理
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=req_timeout,
        )
        response.encoding = 'utf-8'  # 强制使用UTF-8编码
        
        if response.status_code == 200:
            try:
                resp_json = response.json()
                if "code" in resp_json and resp_json['code'] == 0 and resp_json['success']:
                    logger.info(f"[卡密解绑] 解绑成功")
                    return resp_json
                else:
                    error_msg = resp_json['data']['msg']
                    logger.error(f"[卡密解绑] 错误: {error_msg}")
                    return resp_json
            except json.JSONDecodeError as je:
                logger.error(f"[卡密解绑] JSON解析错误: {str(je)}")
                return {"code": -1, "success": False, "data": {"msg": f"解绑响应解析失败: {str(je)}"}}
        else:
            try:
                resp_json = response.json()
                error_msg = resp_json['data']['msg']
            except:
                error_msg = response.text
            logger.error(f"[卡密解绑] 错误码: {response.status_code}, {error_msg}")
            return {"code": -1, "success": False, "data": {"msg": f"解绑请求失败: {error_msg}"}}

    except RequestException as e:
        logger.error(f"[卡密解绑] 请求过程中发生错误: {str(e)}")
        return {"code": -1, "success": False, "data": {"msg": f"解绑请求错误: {str(e)}"}}
    except Timeout:
        logger.error("[卡密解绑] 请求超时，请稍后重试。")
        return {"code": -1, "success": False, "data": {"msg": "解绑请求超时"}}
    except Exception as e:
        logger.error(f"[卡密解绑] 发生未知错误: {str(e)}")
        logger.error(traceback.format_exc())
        return {"code": -1, "success": False, "data": {"msg": f"解绑过程发生错误: {str(e)}"}}

if __name__ == "__main__":
    # Decrypting the data
    decrypted_data = "decrypt_data(key, encrypted_data)"
    print("Decrypted:", decrypted_data)
