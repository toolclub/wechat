"""
运行时 ENC(...) 解密模块

在应用启动时扫描 .env 文件，将 ENC(...) 格式的加密值解密后注入 os.environ，
供 pydantic-settings 读取（os.environ 优先于 env_file）。

若密钥文件不存在（开发环境未配置），打印警告后跳过，不影响已有明文变量。
若密钥文件存在但解密失败，抛出异常终止启动（防止用错误密钥跑生产）。
"""
import os
import re
import base64
import logging
from pathlib import Path

logger = logging.getLogger("decrypt_env")

_ENC_RE = re.compile(r"^ENC\((.+)\)$")

_SECRET_CANDIDATES = [
    Path("/opt/secret/chatflow-secret.yml"),          # 容器内挂载路径
    Path("D:/opt/secret/chatflow-secret.yml"),        # Windows 本地路径
]

# .env 文件路径：容器内 /app/../.env 不存在，但 os.environ 已由 docker env_file 注入
# 本地开发：llm-chat/.env
_ENV_FILE = Path(__file__).parent.parent / ".env"


def _get_fernet():
    import yaml
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.fernet import Fernet

    secret_file = next((p for p in _SECRET_CANDIDATES if p.exists()), None)
    if secret_file is None:
        return None  # 无密钥文件，跳过解密

    with open(secret_file, encoding="utf-8") as f:
        secret = yaml.safe_load(f) or {}

    password = str(secret.get("password", "")).strip()
    salt_hex = str(secret.get("salt", "")).strip()

    if not password or not salt_hex:
        logger.warning("密钥文件格式不完整（缺少 password 或 salt）：%s", secret_file)
        return None

    salt = bytes.fromhex(salt_hex)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return Fernet(key)


def load_encrypted_env() -> bool:
    """
    扫描 .env 文件和 os.environ，解密所有 ENC(...) 值并写回 os.environ。
    返回 True 表示处理了至少一个加密值；False 表示跳过（无加密值或无密钥文件）。
    """
    from cryptography.fernet import InvalidToken

    # 收集所有需要解密的 key→ENC(...) 映射
    # 来源1：.env 文件（本地开发 / 直接运行）
    enc_map: dict[str, str] = {}
    if _ENV_FILE.exists():
        with open(_ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if k and _ENC_RE.match(v):
                        enc_map[k] = v

    # 来源2：os.environ（docker env_file 注入的情况）
    for k, v in os.environ.items():
        if _ENC_RE.match(v):
            enc_map[k] = v

    if not enc_map:
        return False  # 没有需要解密的值

    fernet = _get_fernet()
    if fernet is None:
        logger.warning(
            "发现 %d 个 ENC(...) 加密变量，但密钥文件不存在，已跳过解密。"
            "如需解密请确保 %s 存在。",
            len(enc_map), _SECRET_CANDIDATES[0],
        )
        return False

    count = 0
    for k, enc_v in enc_map.items():
        m = _ENC_RE.match(enc_v)
        if not m:
            continue
        try:
            plain = fernet.decrypt(m.group(1).encode()).decode()
            os.environ[k] = plain
            count += 1
        except InvalidToken as e:
            raise RuntimeError(
                f"解密环境变量 {k} 失败（密码错误或数据损坏），无法启动。"
            ) from e

    logger.info("已解密 %d 个环境变量（ENC→明文）", count)
    return True
