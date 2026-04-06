"""SSL 管理器模块测试"""
import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import sys
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ssl_manager import SSLManager, CertificateInfo


class TestSSLManagerInit:
    """测试 SSLManager 初始化"""
    
    def test_init_creates_directories(self):
        """测试初始化创建目录"""
        with tempfile.TemporaryDirectory() as temp_dir:
            ssl_dir = Path(temp_dir) / "ssl"
            manager = SSLManager(str(ssl_dir))
            
            assert manager.ssl_dir.exists()
            assert manager.certs_dir.exists()
            assert manager.keys_dir.exists()
            assert manager.config_dir.exists()
    
    def test_init_default_path(self):
        """测试默认路径初始化"""
        manager = SSLManager("docker/ssl")
        assert manager.ssl_dir == Path("docker/ssl")
        assert manager.certs_dir == Path("docker/ssl/certs")
        assert manager.keys_dir == Path("docker/ssl/keys")


class TestCertificateInfo:
    """测试 CertificateInfo 数据类"""
    
    def test_to_dict(self):
        """测试转换为字典"""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        info = CertificateInfo(
            subject="CN=localhost",
            issuer="CN=Test CA",
            valid_from=now - timedelta(days=30),
            valid_to=now + timedelta(days=335),
            serial_number="1234567890ABCDEF",
            is_valid=True,
            days_until_expiry=335
        )
        
        result = info.to_dict()
        assert result['subject'] == "CN=localhost"
        assert result['issuer'] == "CN=Test CA"
        assert result['is_valid'] is True
        assert result['days_until_expiry'] == 335
        assert 'valid_from' in result
        assert 'valid_to' in result


class TestGenerateSelfSigned:
    """测试自签名证书生成"""
    
    @patch('app.ssl_manager.subprocess.run')
    @patch('app.ssl_manager.os.chmod')
    def test_generate_success(self, mock_chmod, mock_run):
        """测试生成成功"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.generate_self_signed(cn="localhost", days=365)
            
            assert result is True
            mock_run.assert_called_once()
    
    @patch('app.ssl_manager.subprocess.run')
    def test_generate_failure(self, mock_run):
        """测试生成失败"""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.generate_self_signed(cn="localhost")
            
            assert result is False


class TestCheckCertbot:
    """测试 certbot 检查"""
    
    @patch('app.ssl_manager.subprocess.run')
    def test_certbot_installed(self, mock_run):
        """测试 certbot 已安装"""
        mock_run.return_value = MagicMock(returncode=0, stdout="certbot 1.0", stderr="")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager._check_certbot()
            
            assert result is True
    
    @patch('app.ssl_manager.subprocess.run')
    def test_certbot_not_installed(self, mock_run):
        """测试 certbot 未安装"""
        mock_run.side_effect = FileNotFoundError()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager._check_certbot()
            
            assert result is False


class TestRequestLetsEncrypt:
    """测试 Let's Encrypt 证书申请"""
    
    @patch('app.ssl_manager.SSLManager._check_certbot')
    @patch('app.ssl_manager.subprocess.run')
    @patch('app.ssl_manager.SSLManager._copy_certificate')
    def test_request_success(self, mock_copy, mock_run, mock_check):
        """测试申请成功"""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.request_letsencrypt("example.com", "admin@example.com")
            
            assert result is True
            mock_copy.assert_called_once()
    
    @patch('app.ssl_manager.SSLManager._check_certbot')
    def test_certbot_not_installed(self, mock_check):
        """测试 certbot 未安装"""
        mock_check.return_value = False
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.request_letsencrypt("example.com", "admin@example.com")
            
            assert result is False
    
    @patch('app.ssl_manager.SSLManager._check_certbot')
    @patch('app.ssl_manager.subprocess.run')
    def test_request_failure(self, mock_run, mock_check):
        """测试申请失败"""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.request_letsencrypt("example.com", "admin@example.com")
            
            assert result is False
    
    @patch('app.ssl_manager.SSLManager._check_certbot')
    @patch('app.ssl_manager.subprocess.run')
    def test_request_timeout(self, mock_run, mock_check):
        """测试申请超时"""
        import subprocess
        mock_check.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 120)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.request_letsencrypt("example.com", "admin@example.com")
            
            assert result is False
    
    @patch('app.ssl_manager.SSLManager._check_certbot')
    @patch('app.ssl_manager.subprocess.run')
    def test_test_mode(self, mock_run, mock_check):
        """测试使用 staging 环境"""
        mock_check.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.request_letsencrypt(
                "example.com", 
                "admin@example.com",
                test_mode=True
            )
            
            # 验证使用了 --staging 参数
            call_args = mock_run.call_args[0][0]
            assert "--staging" in call_args


class TestUploadCustomCertificate:
    """测试自定义证书上传"""
    
    @patch('app.ssl_manager.SSLManager._validate_certificate')
    @patch('app.ssl_manager.SSLManager._validate_private_key')
    @patch('app.ssl_manager.SSLManager._match_certificate_key')
    def test_upload_success(self, mock_match, mock_validate_key, mock_validate_cert):
        """测试上传成功"""
        mock_validate_cert.return_value = True
        mock_validate_key.return_value = True
        mock_match.return_value = True
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            
            # 创建测试证书文件
            cert_file = Path(temp_dir) / "test.crt"
            key_file = Path(temp_dir) / "test.key"
            cert_file.write_text("-----BEGIN CERTIFICATE-----")
            key_file.write_text("-----BEGIN PRIVATE KEY-----")
            
            result = manager.upload_custom_certificate(
                str(cert_file),
                str(key_file),
                "custom"
            )
            
            assert result is True
    
    def test_cert_file_not_exists(self):
        """测试证书文件不存在"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.upload_custom_certificate(
                "/nonexistent/cert.crt",
                "/nonexistent/key.key"
            )
            assert result is False
    
    @patch('app.ssl_manager.SSLManager._validate_certificate')
    def test_cert_validation_failed(self, mock_validate):
        """测试证书验证失败"""
        mock_validate.return_value = False
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            
            cert_file = Path(temp_dir) / "test.crt"
            key_file = Path(temp_dir) / "test.key"
            cert_file.write_text("invalid")
            key_file.write_text("invalid")
            
            result = manager.upload_custom_certificate(
                str(cert_file),
                str(key_file)
            )
            assert result is False


class TestValidateCertificate:
    """测试证书验证"""
    
    @patch('app.ssl_manager.subprocess.run')
    def test_valid_certificate(self, mock_run):
        """测试有效证书"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            cert_file = Path(temp_dir) / "test.crt"
            cert_file.write_text("cert content")
            
            result = manager._validate_certificate(cert_file)
            assert result is True
    
    @patch('app.ssl_manager.subprocess.run')
    def test_invalid_certificate(self, mock_run):
        """测试无效证书"""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            cert_file = Path(temp_dir) / "test.crt"
            cert_file.write_text("invalid")
            
            result = manager._validate_certificate(cert_file)
            assert result is False


class TestMatchCertificateKey:
    """测试证书和私钥匹配"""
    
    @patch('app.ssl_manager.subprocess.run')
    def test_match_success(self, mock_run):
        """测试匹配成功"""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="modulus123", stderr=""),
            MagicMock(returncode=0, stdout="modulus123", stderr="")
        ]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            cert_file = Path(temp_dir) / "test.crt"
            key_file = Path(temp_dir) / "test.key"
            
            result = manager._match_certificate_key(cert_file, key_file)
            assert result is True
    
    @patch('app.ssl_manager.subprocess.run')
    def test_match_failure(self, mock_run):
        """测试匹配失败"""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="modulus1", stderr=""),
            MagicMock(returncode=0, stdout="modulus2", stderr="")
        ]
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            cert_file = Path(temp_dir) / "test.crt"
            key_file = Path(temp_dir) / "test.key"
            
            result = manager._match_certificate_key(cert_file, key_file)
            assert result is False


class TestListCertificates:
    """测试列出证书"""
    
    @patch('app.ssl_manager.SSLManager.get_certificate_info')
    def test_list_certificates(self, mock_get_info):
        """测试列出证书"""
        from datetime import datetime, timedelta
        
        mock_get_info.return_value = CertificateInfo(
            subject="CN=localhost",
            issuer="CN=Test CA",
            valid_from=datetime.now() - timedelta(days=30),
            valid_to=datetime.now() + timedelta(days=335),
            serial_number="123456",
            is_valid=True,
            days_until_expiry=335
        )
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            
            # 创建测试证书文件
            cert_file = manager.certs_dir / "test.crt"
            cert_file.write_text("cert content")
            
            result = manager.list_certificates()
            
            assert len(result) == 1
            assert result[0]['name'] == 'test'


class TestEnableSSL:
    """测试启用 SSL"""
    
    @patch('app.ssl_manager.SSLManager.request_letsencrypt')
    def test_enable_letsencrypt(self, mock_request):
        """测试启用 Let's Encrypt"""
        mock_request.return_value = True
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.enable_ssl(
                mode="letsencrypt",
                domain="example.com",
                email="admin@example.com"
            )
            
            assert result['success'] is True
            assert result['mode'] == 'letsencrypt'
    
    @patch('app.ssl_manager.SSLManager.upload_custom_certificate')
    def test_enable_custom(self, mock_upload):
        """测试启用自定义证书"""
        mock_upload.return_value = True
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.enable_ssl(
                mode="custom",
                cert_path="/path/to/cert",
                key_path="/path/to/key"
            )
            
            assert result['success'] is True
            assert result['mode'] == 'custom'
    
    @patch('app.ssl_manager.SSLManager.generate_self_signed')
    def test_enable_self_signed(self, mock_generate):
        """测试启用自签名证书"""
        mock_generate.return_value = True
        
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.enable_ssl(
                mode="self-signed",
                cn="localhost",
                days=365
            )
            
            assert result['success'] is True
            assert result['mode'] == 'self-signed'
    
    def test_enable_unknown_mode(self):
        """测试未知模式"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SSLManager(temp_dir)
            result = manager.enable_ssl(mode="unknown")
            
            assert result['success'] is False
            assert "未知的 SSL 模式" in result['message']
