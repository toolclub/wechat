#!/usr/bin/env python3
"""
ChatFlow 环境变量加密工具

  python envenc.py enc   把 .env 里所有 DEC(...) 加密成 ENC(...)，原地保存
  python envenc.py dec   把 .env 里所有 ENC(...) 解密成 DEC(...)，原地保存

日常流程：
  1. 新增密钥：在 .env 写  MY_KEY=DEC(实际密钥值)
  2. 运行      python envenc.py enc   → .env 里变成  MY_KEY=ENC(加密串)
  3. 提交 .env 到 git（安全，没有明文）

  4. 需要修改密钥：
     python envenc.py dec   → 所有 ENC 展开成 DEC，可以看到明文
     编辑 .env
     python envenc.py enc   → 重新加密

运行时后端自动解密 ENC(...)，无需手动操作。

密钥文件：/opt/secret/chatflow-secret.yml（Windows: D:/opt/secret/chatflow-secret.yml）
依赖：pip install cryptography pyyaml
"""
import os
import re
import sys
import base64
from pathlib import Path

_ENC_RE = re.compile(r"ENC\(([^)]+)\)")
_DEC_RE = re.compile(r"DEC\(([^)]*)\)")

_SECRET_CANDIDATES = [
    Path("/opt/secret/chatflow-secret.yml"),
    Path("D:/opt/secret/chatflow-secret.yml"),
]
_ENV_FILE = Path(__file__).parent / ".env"


def _load_fernet():
    try:
        import yaml
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.fernet import Fernet
    except ImportError:
        print("缺少依赖：pip install cryptography pyyaml", file=sys.stderr)
        sys.exit(1)

    secret_file = next((p for p in _SECRET_CANDIDATES if p.exists()), None)
    if not secret_file:
        print(f"错误：未找到密钥文件，尝试路径：{[str(p) for p in _SECRET_CANDIDATES]}", file=sys.stderr)
        sys.exit(1)

    with open(secret_file, encoding="utf-8") as f:
        secret = yaml.safe_load(f) or {}

    password = str(secret.get("password", "")).strip()
    if not password:
        print(f"错误：密钥文件缺少 password 字段：{secret_file}", file=sys.stderr)
        sys.exit(1)

    if "salt" not in secret:
        salt = os.urandom(16)
        secret["salt"] = salt.hex()
        with open(secret_file, "w", encoding="utf-8") as f:
            yaml.dump(secret, f, allow_unicode=True, default_flow_style=False)
        print(f"[初始化] 已在 {secret_file} 生成 salt", file=sys.stderr)
    else:
        salt = bytes.fromhex(str(secret["salt"]))

    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.fernet import Fernet

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return Fernet(key)


def cmd_enc() -> None:
    """把 .env 里所有 DEC(明文) 加密成 ENC(密文)"""
    if not _ENV_FILE.exists():
        print(f"错误：找不到 {_ENV_FILE}", file=sys.stderr)
        sys.exit(1)

    content = _ENV_FILE.read_text(encoding="utf-8")
    matches = _DEC_RE.findall(content)
    if not matches:
        print("没有找到 DEC(...) 标记，无需加密。")
        return

    fernet = _load_fernet()
    count = 0

    def replace_dec(m: re.Match) -> str:
        nonlocal count
        plaintext = m.group(1)
        token = fernet.encrypt(plaintext.encode()).decode()
        count += 1
        return f"ENC({token})"

    new_content = _DEC_RE.sub(replace_dec, content)
    _ENV_FILE.write_text(new_content, encoding="utf-8")
    print(f"[enc] 已加密 {count} 个值，.env 已更新。")


def cmd_dec() -> None:
    """把 .env 里所有 ENC(密文) 解密成 DEC(明文)"""
    if not _ENV_FILE.exists():
        print(f"错误：找不到 {_ENV_FILE}", file=sys.stderr)
        sys.exit(1)

    content = _ENV_FILE.read_text(encoding="utf-8")
    matches = _ENC_RE.findall(content)
    if not matches:
        print("没有找到 ENC(...) 标记，无需解密。")
        return

    from cryptography.fernet import InvalidToken
    fernet = _load_fernet()
    count = 0

    def replace_enc(m: re.Match) -> str:
        nonlocal count
        try:
            plain = fernet.decrypt(m.group(1).encode()).decode()
            count += 1
            return f"DEC({plain})"
        except InvalidToken:
            print(f"警告：解密失败，跳过：{m.group(0)[:30]}...", file=sys.stderr)
            return m.group(0)

    new_content = _ENC_RE.sub(replace_enc, content)
    _ENV_FILE.write_text(new_content, encoding="utf-8")
    print(f"[dec] 已解密 {count} 个值，.env 已更新。编辑完成后运行 enc 重新加密。")


if __name__ == "__main__":
    cmds = {"enc": cmd_enc, "dec": cmd_dec}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(0)
    cmds[sys.argv[1]]()
