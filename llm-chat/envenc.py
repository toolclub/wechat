#!/usr/bin/env python3
"""
ChatFlow 环境变量加密工具

  python envenc.py enc         加密所有 env 文件
  python envenc.py enc win     仅加密 .env（Windows）
  python envenc.py enc dev     仅加密 .env.dev（Mac 开发）
  python envenc.py enc prod    仅加密 .env.prod（Mac 生产）
  python envenc.py dec         解密所有 env 文件

日常流程：
  1. 新增密钥：在 env 文件写 MY_KEY=DEC(实际密钥值)
  2. 运行      python envenc.py enc   → DEC 变成 ENC(加密串)
  3. 提交到 git（安全，没有明文）

  4. 需要修改密钥：
     python envenc.py dec   → 所有 ENC 展开成 DEC
     编辑 env 文件
     python envenc.py enc   → 重新加密

密钥文件：/opt/secret/chatflow-secret.yml（Windows: D:/opt/secret/chatflow-secret.yml）
依赖：pip install cryptography pyyaml
"""
import os
import re
import sys
from pathlib import Path

_ENC_RE = re.compile(r"ENC\(([^)]+)\)")
_DEC_RE = re.compile(r"DEC\(([^)]*)\)")

_SECRET_CANDIDATES = [
    Path("/opt/secret/chatflow-secret.yml"),
    Path("D:/opt/secret/chatflow-secret.yml"),
]
_BASE = Path(__file__).parent
_ENV_FILES = {
    "win":  _BASE / ".env",
    "dev":  _BASE / ".env.dev",
    "prod": _BASE / ".env.prod",
}


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

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = __import__("base64").urlsafe_b64encode(kdf.derive(password.encode()))
    return Fernet(key)


def _enc_file(env_file: Path, fernet) -> int:
    if not env_file.exists():
        print(f"  (跳过，文件不存在: {env_file.name})")
        return 0
    content = env_file.read_text(encoding="utf-8")
    matches = _DEC_RE.findall(content)
    if not matches:
        return 0
    count = 0
    def replace_dec(m):
        nonlocal count
        token = fernet.encrypt(m.group(1).encode()).decode()
        count += 1
        return f"ENC({token})"
    env_file.write_text(_DEC_RE.sub(replace_dec, content), encoding="utf-8")
    return count


def _dec_file(env_file: Path, fernet) -> int:
    if not env_file.exists():
        return 0
    content = env_file.read_text(encoding="utf-8")
    matches = _ENC_RE.findall(content)
    if not matches:
        return 0
    count = 0
    def replace_enc(m):
        nonlocal count
        try:
            plain = fernet.decrypt(m.group(1).encode()).decode()
            count += 1
            return f"DEC({plain})"
        except Exception:
            print(f"  (解密失败: {m.group(0)[:30]}...)", file=sys.stderr)
            return m.group(0)
    env_file.write_text(_ENC_RE.sub(replace_enc, content), encoding="utf-8")
    return count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in ("enc", "dec"):
        print(__doc__)
        sys.exit(0)

    target = sys.argv[2] if len(sys.argv) > 2 else "all"

    if target == "all":
        files = list(_ENV_FILES.items())
    elif target in _ENV_FILES:
        files = [(target, _ENV_FILES[target])]
    else:
        print(f"错误：未知目标 '{target}'，可选: all, {', '.join(_ENV_FILES.keys())}", file=sys.stderr)
        sys.exit(1)

    fernet = _load_fernet()

    total = 0
    for name, path in files:
        if cmd == "enc":
            n = _enc_file(path, fernet)
            if n:
                print(f"[enc] {path.name}: {n} 个值已加密")
                total += n
        else:
            n = _dec_file(path, fernet)
            if n:
                print(f"[dec] {path.name}: {n} 个值已解密")
                total += n

    if total == 0:
        if cmd == "enc":
            print("没有找到 DEC(...) 标记，无需加密。")
        else:
            print("没有找到 ENC(...) 标记，无需解密。")
    else:
        if cmd == "enc":
            print(f"\n共加密 {total} 个值，可以提交到 git。")
        else:
            print(f"\n共解密 {total} 个值，编辑完成后运行 enc 重新加密。")
