#!/usr/bin/env python3
# Test file for the Linux Server Backup Agent

import os
import sys
import pytest
import tempfile
import yaml
import subprocess
from unittest.mock import patch, MagicMock, mock_open
from main import BackupAgent

class TestBackupAgent:
    """Test class for the BackupAgent"""
    
    @pytest.fixture
    def valid_config(self):
        """Fixture that returns a valid configuration dictionary"""
        return {
            'SYSTEM': {
                'server_name': 'foobar.com'
            },
            'DB': {
                'db_type': 'mysql',
                'db_host': '127.0.0.1',
                'db_user': 'root',
                'db_password': '',
                'db_name': '--all-databases'
            },
            'FILES': {
                'files_dir_path': '/var/www/something/current'
            },
            'BACKUP': {
                'destination_type': 'local',
                'keep_local_copy': True,
                'keep_backups': 5
            },
            'LOGS': {
                'keep_logs': 5
            },
            'FTP': {
                'host': 'ftp.example.com',
                'port': 21,
                'username': 'ftpuser',
                'password': 'ftppassword',
                'remote_dir': '/backups',
                'passive_mode': True
            },
            'SFTP': {
                'host': 'sftp.example.com',
                'port': 22,
                'username': 'sftpuser',
                'password': 'sftppassword',
                'private_key_path': '',
                'remote_dir': '/backups'
            }
        }
    
    @pytest.fixture
    def agent_with_mock_config(self, valid_config):
        """Fixture that returns a BackupAgent with mocked configuration"""
        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            yaml.dump(valid_config, temp_file)
            config_path = temp_file.name
        
        # Create agent with the temp config file
        agent = BackupAgent(config_path)
        
        # Mock the config validation to always return True
        agent.validate_config = MagicMock(return_value=True)
        agent.config = valid_config
        
        yield agent
        
        # Cleanup
        os.unlink(config_path)
    
    def test_init(self):
        """Test the initialization of the BackupAgent"""
        agent = BackupAgent()
        assert agent.config_path == "config.yaml"
        assert agent.config is None
        assert agent.server_name is not None
        assert agent.temp_dir.startswith("/tmp/backup_")
    
    def test_load_config_from_env(self):
        """Test loading configuration from environment variables"""
        # Set environment variables
        env_vars = {
            'BACKITUP_SERVER_NAME': 'env-server',
            'BACKITUP_DB_TYPE': 'mysql',
            'BACKITUP_DB_HOST': '192.168.1.1',
            'BACKITUP_DB_USER': 'dbuser',
            'BACKITUP_DB_PASSWORD': 'dbpass',
            'BACKITUP_DB_NAME': 'testdb',
            'BACKITUP_FILES_DIR_PATH': '/var/www/html',
            'BACKITUP_DESTINATION_TYPE': 'ftp',
            'BACKITUP_KEEP_LOCAL_COPY': 'true',
            'BACKITUP_KEEP_BACKUPS': '3',
            'BACKITUP_FTP_HOST': 'ftp.test.com',
            'BACKITUP_FTP_PORT': '2121',
            'BACKITUP_FTP_USERNAME': 'ftpuser',
            'BACKITUP_FTP_PASSWORD': 'ftppass',
            'BACKITUP_FTP_REMOTE_DIR': '/backups',
            'BACKITUP_FTP_PASSIVE_MODE': 'false',
            'BACKITUP_SFTP_HOST': 'sftp.test.com',
            'BACKITUP_SFTP_PORT': '2222',
            'BACKITUP_SFTP_USERNAME': 'sftpuser',
            'BACKITUP_SFTP_PASSWORD': 'sftppass',
            'BACKITUP_SFTP_PRIVATE_KEY_PATH': '/path/to/key',
            'BACKITUP_SFTP_REMOTE_DIR': '/sftp/backups'
        }
        
        with patch.dict(os.environ, env_vars):
            agent = BackupAgent()
            config = agent.load_config_from_env()
            
            # Check that the configuration was loaded correctly
            assert config['SYSTEM']['server_name'] == 'env-server'
            assert config['DB']['db_type'] == 'mysql'
            assert config['DB']['db_host'] == '192.168.1.1'
            assert config['DB']['db_user'] == 'dbuser'
            assert config['DB']['db_password'] == 'dbpass'
            assert config['DB']['db_name'] == 'testdb'
            assert config['FILES']['files_dir_path'] == '/var/www/html'
            assert config['BACKUP']['destination_type'] == 'ftp'
            assert config['BACKUP']['keep_local_copy'] is True
            assert config['BACKUP']['keep_backups'] == 3
            assert config['FTP']['host'] == 'ftp.test.com'
            assert config['FTP']['port'] == 2121
            assert config['FTP']['username'] == 'ftpuser'
            assert config['FTP']['password'] == 'ftppass'
            assert config['FTP']['remote_dir'] == '/backups'
            assert config['FTP']['passive_mode'] is False
            assert config['SFTP']['host'] == 'sftp.test.com'
            assert config['SFTP']['port'] == 2222
            assert config['SFTP']['username'] == 'sftpuser'
            assert config['SFTP']['password'] == 'sftppass'
            assert config['SFTP']['private_key_path'] == '/path/to/key'
            assert config['SFTP']['remote_dir'] == '/sftp/backups'
    
    def test_load_config_from_env_partial(self):
        """Test loading partial configuration from environment variables"""
        # Set only some environment variables
        env_vars = {
            'BACKITUP_SERVER_NAME': 'env-server',
            'BACKITUP_DB_TYPE': 'mysql',
            'BACKITUP_DB_HOST': '192.168.1.1',
            'BACKITUP_FILES_DIR_PATH': '/var/www/html'
        }
        
        with patch.dict(os.environ, env_vars):
            agent = BackupAgent()
            config = agent.load_config_from_env()
            
            # Check that only the specified variables were loaded
            assert config['SYSTEM']['server_name'] == 'env-server'
            assert config['DB']['db_type'] == 'mysql'
            assert config['DB']['db_host'] == '192.168.1.1'
            assert config['FILES']['files_dir_path'] == '/var/www/html'
            assert 'BACKUP' not in config
            assert 'FTP' not in config
            assert 'SFTP' not in config
    
    def test_load_config_from_env_empty(self):
        """Test loading configuration when no environment variables are set"""
        # Clear all relevant environment variables
        env_vars = {}
        for key in os.environ.keys():
            if key.startswith('BACKITUP_'):
                env_vars[key] = ''
        
        with patch.dict(os.environ, env_vars, clear=True):
            agent = BackupAgent()
            config = agent.load_config_from_env()
            
            # Check that the configuration is empty
            assert config == {}
    
    def test_merge_configs(self):
        """Test merging YAML and environment variable configurations"""
        # Create YAML config
        yaml_config = {
            'SYSTEM': {
                'server_name': 'yaml-server'
            },
            'DB': {
                'db_type': 'mysql',
                'db_host': '127.0.0.1',
                'db_user': 'root',
                'db_password': '',
                'db_name': '--all-databases'
            },
            'FILES': {
                'files_dir_path': '/var/www/yaml'
            },
            'BACKUP': {
                'destination_type': 'local',
                'keep_local_copy': True,
                'keep_backups': 5
            }
        }
        
        # Create env config
        env_config = {
            'SYSTEM': {
                'server_name': 'env-server'
            },
            'DB': {
                'db_host': '192.168.1.1',
                'db_user': 'dbuser'
            },
            'BACKUP': {
                'keep_backups': 3
            }
        }
        
        agent = BackupAgent()
        merged_config = agent.merge_configs(yaml_config, env_config)
        
        # Check that environment variables take precedence
        assert merged_config['SYSTEM']['server_name'] == 'env-server'
        assert merged_config['DB']['db_type'] == 'mysql'  # From YAML
        assert merged_config['DB']['db_host'] == '192.168.1.1'  # From env
        assert merged_config['DB']['db_user'] == 'dbuser'  # From env
        assert merged_config['DB']['db_password'] == ''  # From YAML
        assert merged_config['DB']['db_name'] == '--all-databases'  # From YAML
        assert merged_config['FILES']['files_dir_path'] == '/var/www/yaml'  # From YAML
        assert merged_config['BACKUP']['destination_type'] == 'local'  # From YAML
        assert merged_config['BACKUP']['keep_local_copy'] is True  # From YAML
        assert merged_config['BACKUP']['keep_backups'] == 3  # From env
    
    def test_merge_configs_env_only(self):
        """Test merging when only environment variables are set"""
        # Create empty YAML config
        yaml_config = {}
        
        # Create env config
        env_config = {
            'SYSTEM': {
                'server_name': 'env-server'
            },
            'DB': {
                'db_type': 'mysql',
                'db_host': '192.168.1.1'
            },
            'FILES': {
                'files_dir_path': '/var/www/html'
            }
        }
        
        agent = BackupAgent()
        merged_config = agent.merge_configs(yaml_config, env_config)
        
        # Check that environment variables are used
        assert merged_config['SYSTEM']['server_name'] == 'env-server'
        assert merged_config['DB']['db_type'] == 'mysql'
        assert merged_config['DB']['db_host'] == '192.168.1.1'
        assert merged_config['FILES']['files_dir_path'] == '/var/www/html'
    
    def test_merge_configs_yaml_only(self):
        """Test merging when only YAML configuration is set"""
        # Create YAML config
        yaml_config = {
            'SYSTEM': {
                'server_name': 'yaml-server'
            },
            'DB': {
                'db_type': 'mysql',
                'db_host': '127.0.0.1'
            },
            'FILES': {
                'files_dir_path': '/var/www/yaml'
            }
        }
        
        # Create empty env config
        env_config = {}
        
        agent = BackupAgent()
        merged_config = agent.merge_configs(yaml_config, env_config)
        
        # Check that YAML configuration is used
        assert merged_config['SYSTEM']['server_name'] == 'yaml-server'
        assert merged_config['DB']['db_type'] == 'mysql'
        assert merged_config['DB']['db_host'] == '127.0.0.1'
        assert merged_config['FILES']['files_dir_path'] == '/var/www/yaml'
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="SYSTEM:\n  server_name: foobar.com\nDB:\n  db_type: mysql\n  db_host: 127.0.0.1\nFILES:\n  files_dir_path: /var/www/something/current")
    def test_validate_config_valid(self, mock_file, mock_exists):
        """Test validation of a valid configuration file"""
        # Set up mock to return True for all paths
        mock_exists.return_value = True
        
        agent = BackupAgent()
        result = agent.validate_config()
        
        assert result is True
        # Verify that exists was called with the config path (among other calls)
        mock_exists.assert_any_call(agent.config_path)
        mock_file.assert_called_once_with(agent.config_path, 'r')
    
    @patch('os.path.exists')
    def test_validate_config_file_not_found_no_env(self, mock_exists):
        """Test validation when config file doesn't exist and no environment variables are set"""
        # Set up mock to return different values based on the path
        def side_effect(path):
            if path == "config.yaml":
                return False
            return True
            
        mock_exists.side_effect = side_effect
        
        # Clear all relevant environment variables
        env_vars = {}
        for key in os.environ.keys():
            if key.startswith('BACKITUP_'):
                env_vars[key] = ''
        
        with patch.dict(os.environ, env_vars, clear=True):
            agent = BackupAgent()
            result = agent.validate_config()
            
            assert result is False
            # Verify that exists was called with the config path
            mock_exists.assert_any_call(agent.config_path)
    
    @patch('os.path.exists')
    def test_validate_config_file_not_found_with_env(self, mock_exists):
        """Test validation when config file doesn't exist but environment variables are set"""
        # Set up mock to return different values based on the path
        def side_effect(path):
            if path == "config.yaml":
                return False
            return True
            
        mock_exists.side_effect = side_effect
        
        # Set required environment variables
        env_vars = {
            'BACKITUP_SERVER_NAME': 'env-server',
            'BACKITUP_DB_TYPE': 'mysql',
            'BACKITUP_DB_HOST': '192.168.1.1',
            'BACKITUP_FILES_DIR_PATH': '/var/www/html'
        }
        
        with patch.dict(os.environ, env_vars):
            agent = BackupAgent()
            
            # Mock the files directory to exist
            with patch('os.path.exists') as mock_path_exists:
                def path_exists_side_effect(path):
                    if path == "config.yaml":
                        return False
                    if path == "/var/www/html":
                        return True
                    return True
                
                mock_path_exists.side_effect = path_exists_side_effect
                
                result = agent.validate_config()
                
                assert result is True
                # Verify that exists was called with the config path
                mock_path_exists.assert_any_call(agent.config_path)
                # Verify that exists was called with the files directory
                mock_path_exists.assert_any_call('/var/www/html')
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="invalid yaml content")
    @patch('yaml.safe_load')
    def test_validate_config_invalid_yaml(self, mock_yaml_load, mock_file, mock_exists):
        """Test validation with invalid YAML content"""
        mock_exists.return_value = True
        mock_yaml_load.side_effect = yaml.YAMLError("Invalid YAML")
        
        agent = BackupAgent()
        result = agent.validate_config()
        
        assert result is False
        # Verify that exists was called with the config path
        mock_exists.assert_any_call(agent.config_path)
        mock_file.assert_called_once_with(agent.config_path, 'r')
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="SYSTEM:\n  server_name: foobar.com\nDB:\n  db_host: 127.0.0.1\nFILES:\n  files_dir_path: /var/www/something/current")
    def test_validate_config_missing_required_field(self, mock_file, mock_exists):
        """Test validation with missing required field (db_type)"""
        mock_exists.return_value = True
        
        agent = BackupAgent()
        result = agent.validate_config()
        
        assert result is False
        # Verify that exists was called with the config path
        mock_exists.assert_any_call(agent.config_path)
        mock_file.assert_called_once_with(agent.config_path, 'r')
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="SYSTEM:\n  server_name: foobar.com\nDB:\n  db_host: 127.0.0.1\nFILES:\n  files_dir_path: /var/www/something/current")
    def test_validate_config_missing_field_with_env(self, mock_file, mock_exists):
        """Test validation with missing required field in YAML but provided in environment variables"""
        mock_exists.return_value = True
        
        # Set the missing field in environment variables
        env_vars = {
            'BACKITUP_DB_TYPE': 'mysql'
        }
        
        with patch.dict(os.environ, env_vars):
            agent = BackupAgent()
            
            # Mock the files directory to exist
            with patch('os.path.exists') as mock_path_exists:
                def path_exists_side_effect(path):
                    if path == "/var/www/something/current":
                        return True
                    return True
                
                mock_path_exists.side_effect = path_exists_side_effect
                
                result = agent.validate_config()
                
                assert result is True
    
    @patch('subprocess.run')
    def test_backup_database(self, mock_run, agent_with_mock_config):
        """Test database backup functionality"""
        # Mock subprocess.run to return success
        process_mock = MagicMock()
        process_mock.returncode = 0
        process_mock.stderr = ""
        mock_run.return_value = process_mock
        
        # Mock tarfile operations
        with patch('tarfile.open'), \
             patch('os.remove'):
            
            result = agent_with_mock_config.backup_database()
            
            # Check that the result is not None (indicating success)
            assert result is not None
            
            # Verify mysqldump was called with correct parameters
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert args[0][0] == "mysqldump"
            assert "-u" in args[0]
            assert "-h" in args[0]
            assert "127.0.0.1" in args[0]
    
    @patch('tarfile.open')
    def test_backup_files(self, mock_tarfile, agent_with_mock_config):
        """Test files backup functionality"""
        # Mock tarfile.open to return a context manager
        mock_tar = MagicMock()
        mock_tarfile.return_value.__enter__.return_value = mock_tar
        
        result = agent_with_mock_config.backup_files()
        
        # Check that the result is not None (indicating success)
        assert result is not None
        
        # Verify tarfile operations
        mock_tarfile.assert_called_once()
        mock_tar.add.assert_called_once()
    
    @patch('tarfile.open')
    def test_combine_backups(self, mock_tarfile, agent_with_mock_config):
        """Test combining backups functionality"""
        # Mock tarfile.open to return a context manager
        mock_tar = MagicMock()
        mock_tarfile.return_value.__enter__.return_value = mock_tar
        
        # Create dummy backup paths
        db_backup_path = "/tmp/db_backup.tar.gz"
        files_backup_path = "/tmp/files_backup.tar.gz"
        
        result = agent_with_mock_config.combine_backups(db_backup_path, files_backup_path)
        
        # Check that the result is not None (indicating success)
        assert result is not None
        
        # Verify tarfile operations
        mock_tarfile.assert_called_once()
        assert mock_tar.add.call_count == 2
    
    @patch('shutil.rmtree')
    def test_cleanup(self, mock_rmtree, agent_with_mock_config):
        """Test cleanup functionality"""
        agent_with_mock_config.cleanup()
        
        # Verify rmtree was called with the temp directory
        mock_rmtree.assert_called_once_with(agent_with_mock_config.temp_dir)
    
    def test_run_validation_failure(self, agent_with_mock_config):
        """Test run method when validation fails"""
        # Override the mocked validate_config to return False
        agent_with_mock_config.validate_config = MagicMock(return_value=False)
        
        result = agent_with_mock_config.run()
        
        # Check that the result is False (indicating failure)
        assert result is False
        
        # Verify validate_config was called
        agent_with_mock_config.validate_config.assert_called_once()
    
    def test_execute_command(self, agent_with_mock_config):
        """Test execute_command method"""
        # Set up the agent with a command
        agent_with_mock_config.config.setdefault('COMMANDS', {})
        agent_with_mock_config.config['COMMANDS']['pre_backup'] = "echo 'test command'"
        
        # Mock subprocess.run to return success
        with patch('subprocess.run') as mock_run:
            process_mock = MagicMock()
            process_mock.returncode = 0
            process_mock.stdout = "test output"
            process_mock.stderr = ""
            mock_run.return_value = process_mock
            
            # Test the method
            result = agent_with_mock_config.execute_command('pre_backup')
            
            # Check that the result is True (indicating success)
            assert result is True
            
            # Verify subprocess.run was called with the correct command
            mock_run.assert_called_once_with("echo 'test command'", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    def test_execute_command_failure(self, agent_with_mock_config):
        """Test execute_command method with command failure"""
        # Set up the agent with a command
        agent_with_mock_config.config.setdefault('COMMANDS', {})
        agent_with_mock_config.config['COMMANDS']['pre_backup'] = "invalid_command"
        
        # Mock subprocess.run to return failure
        with patch('subprocess.run') as mock_run:
            process_mock = MagicMock()
            process_mock.returncode = 1
            process_mock.stdout = ""
            process_mock.stderr = "command not found"
            mock_run.return_value = process_mock
            
            # Test the method
            result = agent_with_mock_config.execute_command('pre_backup')
            
            # Check that the result is False (indicating failure)
            assert result is False
            
            # Verify subprocess.run was called with the correct command
            mock_run.assert_called_once_with("invalid_command", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    def test_execute_command_no_command(self, agent_with_mock_config):
        """Test execute_command method with no command configured"""
        # Ensure no command is configured
        if 'COMMANDS' in agent_with_mock_config.config:
            agent_with_mock_config.config['COMMANDS'] = {}
        
        # Test the method
        result = agent_with_mock_config.execute_command('pre_backup')
        
        # Check that the result is True (indicating success, as no command was configured)
        assert result is True
    
    @patch('main.BackupAgent.backup_database')
    @patch('main.BackupAgent.backup_files')
    @patch('main.BackupAgent.combine_backups')
    @patch('main.BackupAgent.send_backup')
    @patch('main.BackupAgent.execute_command')
    @patch('main.BackupAgent.cleanup')
    def test_run_success(self, mock_cleanup, mock_execute_command, mock_send, mock_combine, mock_backup_files, mock_backup_db, agent_with_mock_config):
        """Test run method with successful execution"""
        # Mock all the methods to return success
        mock_backup_db.return_value = "/tmp/db_backup.tar.gz"
        mock_backup_files.return_value = "/tmp/files_backup.tar.gz"
        mock_combine.return_value = "/tmp/combined_backup.tar.gz"
        mock_send.return_value = True
        mock_execute_command.return_value = True
        
        result = agent_with_mock_config.run()
        
        # Check that the result is True (indicating success)
        assert result is True
        
        # Verify all methods were called
        mock_execute_command.assert_any_call('pre_backup')
        mock_backup_db.assert_called_once()
        mock_backup_files.assert_called_once()
        mock_combine.assert_called_once_with("/tmp/db_backup.tar.gz", "/tmp/files_backup.tar.gz")
        mock_execute_command.assert_any_call('post_backup')
        mock_send.assert_called_once_with("/tmp/combined_backup.tar.gz")
        mock_cleanup.assert_called_once_with("/tmp/combined_backup.tar.gz")
        mock_execute_command.assert_any_call('post_transfer')
    
    @patch('main.BackupAgent.backup_database')
    @patch('main.BackupAgent.cleanup')
    def test_run_db_backup_failure(self, mock_cleanup, mock_backup_db, agent_with_mock_config):
        """Test run method when database backup fails"""
        # Mock backup_database to return None (indicating failure)
        mock_backup_db.return_value = None
        
        result = agent_with_mock_config.run()
        
        # Check that the result is False (indicating failure)
        assert result is False
        
        # Verify methods were called
        mock_backup_db.assert_called_once()
        mock_cleanup.assert_called_once()
    
    @patch('main.BackupAgent.backup_database')
    @patch('main.BackupAgent.backup_files')
    @patch('main.BackupAgent.cleanup')
    def test_run_files_backup_failure(self, mock_cleanup, mock_backup_files, mock_backup_db, agent_with_mock_config):
        """Test run method when files backup fails"""
        # Mock backup_database to return success but backup_files to fail
        mock_backup_db.return_value = "/tmp/db_backup.tar.gz"
        mock_backup_files.return_value = None
        
        result = agent_with_mock_config.run()
        
        # Check that the result is False (indicating failure)
        assert result is False
        
        # Verify methods were called
        mock_backup_db.assert_called_once()
        mock_backup_files.assert_called_once()
        mock_cleanup.assert_called_once()
    
    @patch('main.BackupAgent.backup_database')
    @patch('main.BackupAgent.backup_files')
    @patch('main.BackupAgent.combine_backups')
    @patch('main.BackupAgent.cleanup')
    def test_run_combine_failure(self, mock_cleanup, mock_combine, mock_backup_files, mock_backup_db, agent_with_mock_config):
        """Test run method when combining backups fails"""
        # Mock backup methods to succeed but combine to fail
        mock_backup_db.return_value = "/tmp/db_backup.tar.gz"
        mock_backup_files.return_value = "/tmp/files_backup.tar.gz"
        mock_combine.return_value = None
        
        result = agent_with_mock_config.run()
        
        # Check that the result is False (indicating failure)
        assert result is False
        
        # Verify methods were called
        mock_backup_db.assert_called_once()
        mock_backup_files.assert_called_once()
        mock_combine.assert_called_once_with("/tmp/db_backup.tar.gz", "/tmp/files_backup.tar.gz")
        mock_cleanup.assert_called_once()


    @patch('ftplib.FTP')
    def test_send_to_ftp(self, mock_ftp_class, agent_with_mock_config):
        """Test sending backup to FTP server"""
        # Set up the agent to use FTP
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'ftp'
        
        # Mock FTP instance
        mock_ftp = MagicMock()
        mock_ftp_class.return_value = mock_ftp
        
        # Create a temporary file to simulate a backup
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"test backup content")
            backup_path = temp_file.name
        
        try:
            # Test the FTP upload
            result = agent_with_mock_config.send_to_ftp(backup_path)
            
            # Check that the result is True (indicating success)
            assert result is True
            
            # Verify FTP methods were called
            mock_ftp.connect.assert_called_once_with('ftp.example.com', 21)
            mock_ftp.login.assert_called_once_with('ftpuser', 'ftppassword')
            mock_ftp.set_pasv.assert_called_once_with(True)
            mock_ftp.storbinary.assert_called_once()
            mock_ftp.quit.assert_called_once()
        finally:
            # Clean up the temporary file
            os.unlink(backup_path)
    
    @patch('paramiko.Transport')
    @patch('paramiko.SFTPClient')
    def test_send_to_sftp(self, mock_sftp_client_class, mock_transport_class, agent_with_mock_config, monkeypatch):
        """Test sending backup to SFTP server"""
        # Mock paramiko availability
        monkeypatch.setattr('main.PARAMIKO_AVAILABLE', True)
        
        # Set up the agent to use SFTP
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'sftp'
        
        # Mock Transport and SFTPClient instances
        mock_transport = MagicMock()
        mock_transport_class.return_value = mock_transport
        
        mock_sftp = MagicMock()
        mock_sftp_client_class.from_transport.return_value = mock_sftp
        
        # Create a temporary file to simulate a backup
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"test backup content")
            backup_path = temp_file.name
        
        try:
            # Test the SFTP upload
            result = agent_with_mock_config.send_to_sftp(backup_path)
            
            # Check that the result is True (indicating success)
            assert result is True
            
            # Verify SFTP methods were called
            mock_transport_class.assert_called_once_with(('sftp.example.com', 22))
            mock_transport.connect.assert_called_once_with(username='sftpuser', password='sftppassword')
            mock_sftp_client_class.from_transport.assert_called_once_with(mock_transport)
            mock_sftp.put.assert_called_once()
            mock_sftp.close.assert_called_once()
            mock_transport.close.assert_called_once()
        finally:
            # Clean up the temporary file
            os.unlink(backup_path)
    
    def test_send_backup_local(self, agent_with_mock_config):
        """Test send_backup with local destination"""
        # Set up the agent to use local destination
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'local'
        
        # Create a temporary file to simulate a backup
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            backup_path = temp_file.name
        
        try:
            # Test the local backup
            result = agent_with_mock_config.send_backup(backup_path)
            
            # Check that the result is True (indicating success)
            assert result is True
        finally:
            # Clean up the temporary file
            os.unlink(backup_path)
    
    @patch('main.BackupAgent.send_to_ftp')
    def test_send_backup_ftp(self, mock_send_to_ftp, agent_with_mock_config):
        """Test send_backup with FTP destination"""
        # Set up the agent to use FTP destination
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'ftp'
        mock_send_to_ftp.return_value = True
        
        # Create a temporary file to simulate a backup
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            backup_path = temp_file.name
        
        try:
            # Test the FTP backup
            result = agent_with_mock_config.send_backup(backup_path)
            
            # Check that the result is True (indicating success)
            assert result is True
            
            # Verify send_to_ftp was called
            mock_send_to_ftp.assert_called_once_with(backup_path)
        finally:
            # Clean up the temporary file
            os.unlink(backup_path)
    
    @patch('main.BackupAgent.send_to_sftp')
    def test_send_backup_sftp(self, mock_send_to_sftp, agent_with_mock_config):
        """Test send_backup with SFTP destination"""
        # Set up the agent to use SFTP destination
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'sftp'
        mock_send_to_sftp.return_value = True
        
        # Create a temporary file to simulate a backup
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            backup_path = temp_file.name
        
        try:
            # Test the SFTP backup
            result = agent_with_mock_config.send_backup(backup_path)
            
            # Check that the result is True (indicating success)
            assert result is True
            
            # Verify send_to_sftp was called
            mock_send_to_sftp.assert_called_once_with(backup_path)
        finally:
            # Clean up the temporary file
            os.unlink(backup_path)


    @patch('glob.glob')
    @patch('os.path.getmtime')
    def test_list_local_backups(self, mock_getmtime, mock_glob, agent_with_mock_config):
        """Test listing local backups"""
        # Mock glob.glob to return a list of backup files
        backup_files = [
            f"/path/to/2023-01-01.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"/path/to/2023-01-02.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"/path/to/2023-01-03.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz"
        ]
        mock_glob.return_value = backup_files
        
        # Mock getmtime to return timestamps in order (using a dictionary to map paths to timestamps)
        timestamps = {path: i for i, path in enumerate(backup_files)}
        mock_getmtime.side_effect = lambda x: timestamps[x]
        
        # Test the method
        result = agent_with_mock_config.list_local_backups()
        
        # Check that the result matches the expected list
        assert result == backup_files
        
        # Verify glob was called with the correct pattern
        mock_glob.assert_called_once()
        pattern_arg = mock_glob.call_args[0][0]
        assert f"*_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz" in pattern_arg
    
    @patch('os.remove')
    @patch('main.BackupAgent.list_local_backups')
    def test_delete_old_local_backups(self, mock_list_backups, mock_remove, agent_with_mock_config):
        """Test deleting old local backups"""
        # Set up the agent to keep 2 backups
        agent_with_mock_config.config['BACKUP']['keep_backups'] = 2
        
        # Mock list_local_backups to return a list of backup files
        backup_files = [
            f"/path/to/2023-01-01.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"/path/to/2023-01-02.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"/path/to/2023-01-03.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz"
        ]
        mock_list_backups.return_value = backup_files
        
        # Test the method
        agent_with_mock_config.delete_old_local_backups()
        
        # Verify list_local_backups was called
        mock_list_backups.assert_called_once()
        
        # Verify os.remove was called for the oldest backup
        mock_remove.assert_called_once_with(backup_files[0])
    
    @patch('main.BackupAgent.list_remote_backups_ftp')
    @patch('ftplib.FTP')
    def test_delete_old_remote_backups_ftp(self, mock_ftp_class, mock_list_backups, agent_with_mock_config):
        """Test deleting old remote backups from FTP server"""
        # Set up the agent to use FTP and keep 2 backups
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'ftp'
        agent_with_mock_config.config['BACKUP']['keep_backups'] = 2
        
        # Mock list_remote_backups_ftp to return a list of backup files
        backup_files = [
            f"2023-01-01.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"2023-01-02.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"2023-01-03.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz"
        ]
        mock_list_backups.return_value = backup_files
        
        # Mock FTP instance
        mock_ftp = MagicMock()
        mock_ftp_class.return_value = mock_ftp
        
        # Test the method
        agent_with_mock_config.delete_old_remote_backups_ftp()
        
        # Verify list_remote_backups_ftp was called
        mock_list_backups.assert_called_once()
        
        # Verify FTP methods were called
        mock_ftp.connect.assert_called_once_with('ftp.example.com', 21)
        mock_ftp.login.assert_called_once_with('ftpuser', 'ftppassword')
        mock_ftp.set_pasv.assert_called_once_with(True)
        mock_ftp.cwd.assert_called_once_with('/backups')
        
        # Verify delete was called for the oldest backup
        mock_ftp.delete.assert_called_once_with(backup_files[0])
        mock_ftp.quit.assert_called_once()
    
    @patch('main.BackupAgent.list_remote_backups_sftp')
    @patch('paramiko.Transport')
    @patch('paramiko.SFTPClient')
    def test_delete_old_remote_backups_sftp(self, mock_sftp_client_class, mock_transport_class, mock_list_backups, agent_with_mock_config, monkeypatch):
        """Test deleting old remote backups from SFTP server"""
        # Mock paramiko availability
        monkeypatch.setattr('main.PARAMIKO_AVAILABLE', True)
        
        # Set up the agent to use SFTP and keep 2 backups
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'sftp'
        agent_with_mock_config.config['BACKUP']['keep_backups'] = 2
        
        # Mock list_remote_backups_sftp to return a list of backup files
        backup_files = [
            f"2023-01-01.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"2023-01-02.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz",
            f"2023-01-03.12:00_{agent_with_mock_config.server_name}_root_files_and_db.tar.gz"
        ]
        mock_list_backups.return_value = backup_files
        
        # Mock Transport and SFTPClient instances
        mock_transport = MagicMock()
        mock_transport_class.return_value = mock_transport
        
        mock_sftp = MagicMock()
        mock_sftp_client_class.from_transport.return_value = mock_sftp
        
        # Test the method
        agent_with_mock_config.delete_old_remote_backups_sftp()
        
        # Verify list_remote_backups_sftp was called
        mock_list_backups.assert_called_once()
        
        # Verify SFTP methods were called
        mock_transport_class.assert_called_once_with(('sftp.example.com', 22))
        mock_transport.connect.assert_called_once_with(username='sftpuser', password='sftppassword')
        mock_sftp_client_class.from_transport.assert_called_once_with(mock_transport)
        
        # Verify remove was called for the oldest backup
        mock_sftp.remove.assert_called_once_with(os.path.join('/backups', backup_files[0]))
        mock_sftp.close.assert_called_once()
        mock_transport.close.assert_called_once()
    
    @patch('main.BackupAgent.delete_old_local_backups')
    @patch('main.BackupAgent.delete_old_remote_backups_ftp')
    @patch('main.BackupAgent.delete_old_remote_backups_sftp')
    def test_rotate_backups_local(self, mock_sftp_rotate, mock_ftp_rotate, mock_local_rotate, agent_with_mock_config):
        """Test rotating backups with local destination"""
        # Set up the agent to use local destination
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'local'
        
        # Test the method
        agent_with_mock_config.rotate_backups()
        
        # Verify delete_old_local_backups was called
        mock_local_rotate.assert_called_once()
        
        # Verify other methods were not called
        mock_ftp_rotate.assert_not_called()
        mock_sftp_rotate.assert_not_called()
    
    @patch('main.BackupAgent.delete_old_local_backups')
    @patch('main.BackupAgent.delete_old_remote_backups_ftp')
    @patch('main.BackupAgent.delete_old_remote_backups_sftp')
    def test_rotate_backups_ftp(self, mock_sftp_rotate, mock_ftp_rotate, mock_local_rotate, agent_with_mock_config):
        """Test rotating backups with FTP destination"""
        # Set up the agent to use FTP destination
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'ftp'
        
        # Test the method
        agent_with_mock_config.rotate_backups()
        
        # Verify delete_old_local_backups and delete_old_remote_backups_ftp were called
        mock_local_rotate.assert_called_once()
        mock_ftp_rotate.assert_called_once()
        
        # Verify delete_old_remote_backups_sftp was not called
        mock_sftp_rotate.assert_not_called()
    
    @patch('main.BackupAgent.delete_old_local_backups')
    @patch('main.BackupAgent.delete_old_remote_backups_ftp')
    @patch('main.BackupAgent.delete_old_remote_backups_sftp')
    def test_rotate_backups_sftp(self, mock_sftp_rotate, mock_ftp_rotate, mock_local_rotate, agent_with_mock_config):
        """Test rotating backups with SFTP destination"""
        # Set up the agent to use SFTP destination
        agent_with_mock_config.config['BACKUP']['destination_type'] = 'sftp'
        
        # Test the method
        agent_with_mock_config.rotate_backups()
        
        # Verify delete_old_local_backups and delete_old_remote_backups_sftp were called
        mock_local_rotate.assert_called_once()
        mock_sftp_rotate.assert_called_once()
        
        # Verify delete_old_remote_backups_ftp was not called
        mock_ftp_rotate.assert_not_called()
    
    @patch('glob.glob')
    @patch('os.path.getmtime')
    def test_list_log_files(self, mock_getmtime, mock_glob, agent_with_mock_config):
        """Test listing log files"""
        # Mock glob.glob to return a list of log files
        log_files = [
            "/path/to/[2023-01-01.12:00]_backup.log",
            "/path/to/[2023-01-02.12:00]_backup.log",
            "/path/to/[2023-01-03.12:00]_backup.log"
        ]
        mock_glob.return_value = log_files
        
        # Mock getmtime to return timestamps in order (using a dictionary to map paths to timestamps)
        timestamps = {path: i for i, path in enumerate(log_files)}
        mock_getmtime.side_effect = lambda x: timestamps[x]
        
        # Test the method
        result = agent_with_mock_config.list_log_files()
        
        # Check that the result matches the expected list
        assert result == log_files
        
        # Verify glob was called with the correct pattern
        mock_glob.assert_called_once()
        pattern_arg = mock_glob.call_args[0][0]
        assert "[*]_backup.log" in pattern_arg
    
    @patch('os.remove')
    @patch('main.BackupAgent.list_log_files')
    def test_rotate_logs(self, mock_list_logs, mock_remove, agent_with_mock_config):
        """Test rotating log files"""
        # Set up the agent with LOGS configuration
        agent_with_mock_config.config['LOGS'] = {'keep_logs': 2}
        
        # Mock list_log_files to return a list of log files
        log_files = [
            "/path/to/[2023-01-01.12:00]_backup.log",
            "/path/to/[2023-01-02.12:00]_backup.log",
            "/path/to/[2023-01-03.12:00]_backup.log"
        ]
        mock_list_logs.return_value = log_files
        
        # Test the method
        agent_with_mock_config.rotate_logs()
        
        # Verify list_log_files was called
        mock_list_logs.assert_called_once()
        
        # Verify os.remove was called for the oldest log file
        mock_remove.assert_called_once_with(log_files[0])
    
    @patch('main.BackupAgent.rotate_logs')
    @patch('main.BackupAgent.rotate_backups')
    @patch('main.BackupAgent.backup_database')
    @patch('main.BackupAgent.backup_files')
    @patch('main.BackupAgent.combine_backups')
    @patch('main.BackupAgent.send_backup')
    @patch('main.BackupAgent.cleanup')
    def test_run_with_rotation(self, mock_cleanup, mock_send, mock_combine, mock_backup_files, mock_backup_db, mock_rotate_backups, mock_rotate_logs, agent_with_mock_config):
        """Test run method with backup and log rotation"""
        # Mock all the methods to return success
        mock_backup_db.return_value = "/tmp/db_backup.tar.gz"
        mock_backup_files.return_value = "/tmp/files_backup.tar.gz"
        mock_combine.return_value = "/tmp/combined_backup.tar.gz"
        mock_send.return_value = True
        
        result = agent_with_mock_config.run()
        
        # Check that the result is True (indicating success)
        assert result is True
        
        # Verify all methods were called
        mock_backup_db.assert_called_once()
        mock_backup_files.assert_called_once()
        mock_combine.assert_called_once_with("/tmp/db_backup.tar.gz", "/tmp/files_backup.tar.gz")
        mock_send.assert_called_once_with("/tmp/combined_backup.tar.gz")
        mock_rotate_backups.assert_called_once()
        mock_rotate_logs.assert_called_once()
        mock_cleanup.assert_called_once_with("/tmp/combined_backup.tar.gz")
    
    def test_rotate_logs_no_config(self, agent_with_mock_config):
        """Test rotate_logs method when no LOGS configuration is present"""
        # Remove LOGS section from config if it exists
        if 'LOGS' in agent_with_mock_config.config:
            del agent_with_mock_config.config['LOGS']
        
        # Mock list_log_files to ensure it's not called
        with patch('main.BackupAgent.list_log_files') as mock_list_logs:
            # Test the method
            agent_with_mock_config.rotate_logs()
            
            # Verify list_log_files was not called
            mock_list_logs.assert_not_called()
    
    def test_rotate_logs_disabled(self, agent_with_mock_config):
        """Test rotate_logs method when log rotation is disabled (keep_logs <= 0)"""
        # Set keep_logs to 0 to disable rotation
        agent_with_mock_config.config['LOGS'] = {'keep_logs': 0}
        
        # Mock list_log_files to ensure it's not called
        with patch('main.BackupAgent.list_log_files') as mock_list_logs:
            # Test the method
            agent_with_mock_config.rotate_logs()
            
            # Verify list_log_files was not called
            mock_list_logs.assert_not_called()


if __name__ == "__main__":
    pytest.main(["-v", "test_backup_agent.py"])
