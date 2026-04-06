#!/usr/bin/env python3
"""
Bridge Server SSL Certificate Manager

支持三种证书模式：
1. Let's Encrypt 自动申请
2. 自定义证书上传
3. 自签名证书（开发环境）
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class CertificateInfo:
    """证书信息"""

    subject: str
    issuer: str
    valid_from: datetime
    valid_to: datetime
    serial_number: str
    is_valid: bool
    days_until_expiry: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject,
            "issuer": self.issuer,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
            "serial_number": self.serial_number,
            "is_valid": self.is_valid,
            "days_until_expiry": self.days_until_expiry,
        }


class SSLManager:
    """SSL 证书管理器"""

    def __init__(self, ssl_dir: str = "docker/ssl"):
        """
        初始化 SSL 管理器

        Args:
            ssl_dir: SSL 目录路径
        """
        self.ssl_dir = Path(ssl_dir)
        self.certs_dir = self.ssl_dir / "certs"
        self.keys_dir = self.ssl_dir / "keys"
        self.config_dir = self.ssl_dir / "config"

        # 创建目录结构
        self._ensure_directories()

    def _ensure_directories(self):
        """确保目录存在"""
        for dir_path in [self.certs_dir, self.keys_dir, self.config_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"确保目录存在：{dir_path}")

    def request_letsencrypt(
        self, domain: str, email: str, test_mode: bool = False
    ) -> bool:
        """
        申请 Let's Encrypt 证书

        Args:
            domain: 域名
            email: 邮箱
            test_mode: 是否使用测试环境（staging）

        Returns:
            bool: 是否成功
        """
        logger.info(f"申请 Let's Encrypt 证书：domain={domain}, email={email}")

        # 检查 certbot 是否安装
        if not self._check_certbot():
            logger.error("certbot 未安装")
            return False

        # 构建命令
        cmd = [
            "certbot",
            "certonly",
            "--standalone",
            "--preferred-challenges",
            "http",
            "--email",
            email,
            "--agree-tos",
            "--non-interactive",
            "-d",
            domain,
        ]

        if test_mode:
            cmd.insert(2, "--staging")
            logger.info("使用 Let's Encrypt 测试环境")

        # 执行命令
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0:
                logger.info("Let's Encrypt 证书申请成功")

                # 复制证书到 SSL 目录
                cert_path = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
                key_path = f"/etc/letsencrypt/live/{domain}/privkey.pem"

                self._copy_certificate(domain, cert_path, key_path)

                return True
            else:
                logger.error(f"证书申请失败：{result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("证书申请超时")
            return False
        except Exception as e:
            logger.error(f"证书申请异常：{e}")
            return False

    def _check_certbot(self) -> bool:
        """检查 certbot 是否安装"""
        try:
            result = subprocess.run(
                ["certbot", "--version"], capture_output=True, text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _copy_certificate(self, name: str, cert_path: str, key_path: str):
        """复制证书到 SSL 目录"""
        import shutil

        cert_dest = self.certs_dir / f"{name}.crt"
        key_dest = self.keys_dir / f"{name}.key"

        try:
            shutil.copy2(cert_path, cert_dest)
            shutil.copy2(key_path, key_dest)
            logger.info(f"证书已复制：{cert_dest}, {key_dest}")
        except Exception as e:
            logger.error(f"复制证书失败：{e}")
            raise

    def upload_custom_certificate(
        self, cert_path: str, key_path: str, name: str = "custom"
    ) -> bool:
        """
        上传自定义证书

        Args:
            cert_path: 证书文件路径（PEM 格式）
            key_path: 私钥文件路径（PEM 格式）
            name: 证书名称

        Returns:
            bool: 是否成功
        """
        logger.info(f"上传自定义证书：{name}")

        cert_src = Path(cert_path)
        key_src = Path(key_path)

        # 检查文件是否存在
        if not cert_src.exists():
            logger.error(f"证书文件不存在：{cert_path}")
            return False

        if not key_src.exists():
            logger.error(f"私钥文件不存在：{key_path}")
            return False

        # 验证证书格式
        if not self._validate_certificate(cert_src):
            logger.error("证书格式验证失败")
            return False

        if not self._validate_private_key(key_src):
            logger.error("私钥格式验证失败")
            return False

        # 验证证书和私钥是否匹配
        if not self._match_certificate_key(cert_src, key_src):
            logger.error("证书和私钥不匹配")
            return False

        # 复制文件
        cert_dest = self.certs_dir / f"{name}.crt"
        key_dest = self.keys_dir / f"{name}.key"

        import shutil

        shutil.copy2(cert_src, cert_dest)
        shutil.copy2(key_src, key_dest)

        logger.info(f"自定义证书已保存：{cert_dest}, {key_dest}")
        return True

    def generate_self_signed(
        self, cn: str = "localhost", days: int = 365, name: str = "self-signed"
    ) -> bool:
        """
        生成自签名证书

        Args:
            cn: Common Name（域名或 IP）
            days: 有效期（天）
            name: 证书名称

        Returns:
            bool: 是否成功
        """
        logger.info(f"生成自签名证书：cn={cn}, days={days}")

        cert_path = self.certs_dir / f"{name}.crt"
        key_path = self.keys_dir / f"{name}.key"

        # OpenSSL 命令
        cmd = [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            str(days),
            "-nodes",
            "-subj",
            f"/CN={cn}",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                logger.info(f"自签名证书生成成功：{cert_path}, {key_path}")

                # 设置权限
                os.chmod(key_path, 0o600)

                return True
            else:
                logger.error(f"生成失败：{result.stderr}")
                return False

        except Exception as e:
            logger.error(f"生成异常：{e}")
            return False

    def _validate_certificate(self, cert_path: Path) -> bool:
        """验证证书格式"""
        try:
            result = subprocess.run(
                ["openssl", "x509", "-in", str(cert_path), "-noout", "-text"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"证书验证失败：{e}")
            return False

    def _validate_private_key(self, key_path: Path) -> bool:
        """验证私钥格式"""
        try:
            result = subprocess.run(
                ["openssl", "rsa", "-in", str(key_path), "-check", "-noout"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"私钥验证失败：{e}")
            return False

    def _match_certificate_key(self, cert_path: Path, key_path: Path) -> bool:
        """验证证书和私钥是否匹配"""
        try:
            # 获取证书 modulus
            cert_result = subprocess.run(
                ["openssl", "x509", "-noout", "-modulus", "-in", str(cert_path)],
                capture_output=True,
                text=True,
            )

            # 获取私钥 modulus
            key_result = subprocess.run(
                ["openssl", "rsa", "-noout", "-modulus", "-in", str(key_path)],
                capture_output=True,
                text=True,
            )

            if cert_result.returncode != 0 or key_result.returncode != 0:
                return False

            return cert_result.stdout == key_result.stdout

        except Exception as e:
            logger.error(f"匹配验证失败：{e}")
            return False

    def get_certificate_info(self, name: str) -> Optional[CertificateInfo]:
        """
        获取证书信息

        Args:
            name: 证书名称

        Returns:
            CertificateInfo 或 None
        """
        cert_path = self.certs_dir / f"{name}.crt"

        if not cert_path.exists():
            logger.error(f"证书不存在：{name}")
            return None

        try:
            # 获取证书信息
            result = subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-in",
                    str(cert_path),
                    "-noout",
                    "-subject",
                    "-issuer",
                    "-dates",
                    "-serial",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return None

            # 解析输出
            info = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key.strip()] = value.strip()

            # 解析日期
            valid_from = datetime.strptime(
                info.get("notBefore", ""), "%b %d %H:%M:%S %Y %Z"
            )
            valid_to = datetime.strptime(
                info.get("notAfter", ""), "%b %d %H:%M:%S %Y %Z"
            )

            # 计算剩余天数
            days_until_expiry = (valid_to - datetime.now()).days

            # 检查是否有效
            is_valid = datetime.now() >= valid_from and datetime.now() <= valid_to

            return CertificateInfo(
                subject=info.get("subject", ""),
                issuer=info.get("issuer", ""),
                valid_from=valid_from,
                valid_to=valid_to,
                serial_number=info.get("serial", ""),
                is_valid=is_valid,
                days_until_expiry=days_until_expiry,
            )

        except Exception as e:
            logger.error(f"获取证书信息失败：{e}")
            return None

    def list_certificates(self) -> List[Dict[str, Any]]:
        """列出所有证书"""
        certificates = []

        for cert_file in self.certs_dir.glob("*.crt"):
            name = cert_file.stem
            info = self.get_certificate_info(name)

            if info:
                cert_info = info.to_dict()
                cert_info["name"] = name
                cert_info["cert_path"] = str(cert_file)
                cert_info["key_path"] = str(self.keys_dir / f"{name}.key")
                certificates.append(cert_info)

        return certificates

    def renew_certificate(self, name: str) -> bool:
        """
        续期证书

        Args:
            name: 证书名称

        Returns:
            bool: 是否成功
        """
        info = self.get_certificate_info(name)

        if not info:
            logger.error(f"证书不存在：{name}")
            return False

        # 检查是否需要续期（30 天内过期）
        if info.days_until_expiry > 30:
            logger.info(f"证书不需要续期（剩余{info.days_until_expiry}天）")
            return True

        logger.info(f"证书即将过期（剩余{info.days_until_expiry}天），开始续期")

        # 如果是 Let's Encrypt 证书，使用 certbot 续期
        if name != "self-signed" and name != "custom":
            return self.request_letsencrypt(name, "admin@" + name)

        # 否则重新生成自签名证书
        if name == "self-signed":
            return self.generate_self_signed(cn=name)

        # 自定义证书需要手动上传
        logger.warning("自定义证书需要手动上传新证书")
        return False

    def enable_ssl(self, mode: str = "letsencrypt", **kwargs) -> Dict[str, Any]:
        """
        启用 SSL

        Args:
            mode: 模式（letsencrypt/custom/self-signed）
            **kwargs: 模式相关参数

        Returns:
            Dict: 结果信息
        """
        logger.info(f"启用 SSL，模式：{mode}")

        if mode == "letsencrypt":
            domain = kwargs.get("domain")
            email = kwargs.get("email", "admin@" + domain)
            test_mode = kwargs.get("test_mode", False)

            success = self.request_letsencrypt(domain, email, test_mode)

            return {
                "success": success,
                "mode": mode,
                "domain": domain,
                "message": (
                    "Let's Encrypt 证书申请成功"
                    if success
                    else "Let's Encrypt 证书申请失败"
                ),
            }

        elif mode == "custom":
            cert_path = kwargs.get("cert_path")
            key_path = kwargs.get("key_path")
            name = kwargs.get("name", "custom")

            success = self.upload_custom_certificate(cert_path, key_path, name)

            return {
                "success": success,
                "mode": mode,
                "name": name,
                "message": "自定义证书上传成功" if success else "自定义证书上传失败",
            }

        elif mode == "self-signed":
            cn = kwargs.get("cn", "localhost")
            days = kwargs.get("days", 365)
            name = kwargs.get("name", "self-signed")

            success = self.generate_self_signed(cn, days, name)

            return {
                "success": success,
                "mode": mode,
                "cn": cn,
                "days": days,
                "message": "自签名证书生成成功" if success else "自签名证书生成失败",
            }

        else:
            return {
                "success": False,
                "mode": mode,
                "message": f"未知的 SSL 模式：{mode}",
            }


# CLI 命令
def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="SSL 证书管理器")
    subparsers = parser.add_subparsers(dest="command", help="命令")

    # enable-ssl 命令
    enable_parser = subparsers.add_parser("enable-ssl", help="启用 SSL")
    enable_parser.add_argument(
        "--mode",
        choices=["letsencrypt", "custom", "self-signed"],
        default="self-signed",
    )
    enable_parser.add_argument("--domain", help="域名（Let's Encrypt 模式）")
    enable_parser.add_argument("--email", help="邮箱（Let's Encrypt 模式）")
    enable_parser.add_argument("--cert", help="证书文件路径（自定义模式）")
    enable_parser.add_argument("--key", help="私钥文件路径（自定义模式）")
    enable_parser.add_argument(
        "--cn", default="localhost", help="Common Name（自签名模式）"
    )
    enable_parser.add_argument(
        "--days", type=int, default=365, help="有效期（自签名模式）"
    )
    enable_parser.add_argument(
        "--test", action="store_true", help="使用测试环境（Let's Encrypt）"
    )

    # list 命令
    subparsers.add_parser("list", help="列出所有证书")

    # info 命令
    info_parser = subparsers.add_parser("info", help="查看证书信息")
    info_parser.add_argument("name", help="证书名称")

    # renew 命令
    renew_parser = subparsers.add_parser("renew", help="续期证书")
    renew_parser.add_argument("name", help="证书名称")

    args = parser.parse_args()

    # 初始化 SSL 管理器
    ssl_manager = SSLManager()

    if args.command == "enable-ssl":
        if args.mode == "letsencrypt":
            result = ssl_manager.enable_ssl(
                args.mode, domain=args.domain, email=args.email, test_mode=args.test
            )
        elif args.mode == "custom":
            result = ssl_manager.enable_ssl(
                args.mode, cert_path=args.cert, key_path=args.key
            )
        elif args.mode == "self-signed":
            result = ssl_manager.enable_ssl(args.mode, cn=args.cn, days=args.days)

        print(f"{'✅ 成功' if result['success'] else '❌ 失败'}: {result['message']}")
        sys.exit(0 if result["success"] else 1)

    elif args.command == "list":
        certs = ssl_manager.list_certificates()
        if certs:
            print(f"找到 {len(certs)} 个证书:\n")
            for cert in certs:
                print(f"  📄 {cert['name']}")
                print(
                    f"     有效期：{cert['valid_from'][:10]} ~ {cert['valid_to'][:10]}"
                )
                print(f"     剩余：{cert['days_until_expiry']} 天")
                print(f"     状态：{'✅ 有效' if cert['is_valid'] else '❌ 过期'}")
                print()
        else:
            print("没有找到证书")

    elif args.command == "info":
        info = ssl_manager.get_certificate_info(args.name)
        if info:
            print(f"证书信息：{args.name}")
            print(f"  主题：{info.subject}")
            print(f"  颁发者：{info.issuer}")
            print(f"  有效期：{info.valid_from} ~ {info.valid_to}")
            print(f"  剩余：{info.days_until_expiry} 天")
            print(f"  状态：{'✅ 有效' if info.is_valid else '❌ 过期'}")
        else:
            print(f"证书不存在：{args.name}")
            sys.exit(1)

    elif args.command == "renew":
        success = ssl_manager.renew_certificate(args.name)
        print(f"{'✅ 续期成功' if success else '❌ 续期失败'}")
        sys.exit(0 if success else 1)

    else:
        parser.print_help()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
