#!/usr/bin/env python3
# Linux Server Backup Agent
# This script performs backups of MySQL/MariaDB databases and specified file directories

import os
import sys
import yaml
import subprocess
import tarfile
import logging
import datetime
import shutil
import ftplib
import re
import glob
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Literal, List

# Import paramiko for SFTP if available
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False
    logging.warning("Paramiko not available. SFTP functionality will be disabled.")

# Configure basic console logging for startup messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("backup_agent")

class BackupAgent:
    """
    Agent responsible for creating backups of databases and file directories
    on Linux servers based on YAML configuration.
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the backup agent with the path to the configuration file.
        
        Args:
            config_path: Path to the YAML configuration file (optional if environment variables are set)
        """
        self.config_path = config_path
        self.config = None
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d.%H:%M:%S")
        # Default server name from system, may be overridden by config
        self.server_name = os.uname().nodename
        self.temp_dir = f"/tmp/backup_{self.timestamp}"
        self.log_dir = "logs"  # Default log directory, may be overridden by config
        
        # Ensure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
    
    def setup_logging(self):
        """Set up logging with the configured log directory"""
        # Get log directory from config if available
        if self.config and 'LOGS' in self.config and 'log_dir' in self.config['LOGS']:
            self.log_dir = self.config['LOGS']['log_dir']
        
        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Create log filename without brackets
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d.%H:%M:%S")
        log_filename = os.path.join(self.log_dir, f"{timestamp}_backup.log")
        
        # Configure file handler
        file_handler = logging.FileHandler(log_filename)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        
        # Remove existing handlers and add new ones
        logger = logging.getLogger("backup_agent")
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)
        
        logger.addHandler(file_handler)
        logger.setLevel(logging.INFO)
        
        logger.info(f"Logging to: {log_filename}")
        
    def list_log_files(self) -> List[str]:
        """
        List all existing log files in the log directory.
        
        Returns:
            List[str]: List of log file paths, sorted by date (oldest first)
        """
        try:
            # Get the directory where logs are stored
            if self.config and 'LOGS' in self.config and 'log_dir' in self.config['LOGS']:
                log_dir = self.config['LOGS']['log_dir']
            else:
                log_dir = self.log_dir
            
            # Ensure log directory exists
            os.makedirs(log_dir, exist_ok=True)
            
            # Define the pattern for log files
            pattern = "*_backup.log"
            
            # Find all matching files
            log_files = glob.glob(os.path.join(log_dir, pattern))
            
            # Sort files by modification time (oldest first)
            log_files.sort(key=os.path.getmtime)
            
            logger.info(f"Found {len(log_files)} existing log files in {log_dir}")
            return log_files
        except Exception as e:
            logger.error(f"Error listing log files: {e}")
            return []
    
    def rotate_logs(self):
        """
        Rotate log files based on the configuration, deleting old logs as needed.
        """
        try:
            if 'LOGS' not in self.config:
                logger.info("Log rotation not configured, skipping")
                return
            
            keep_logs = self.config['LOGS'].get('keep_logs', 0)
            if keep_logs <= 0:
                logger.info("Log rotation disabled (keep_logs <= 0)")
                return
            
            # Update log directory from config if specified
            if 'log_dir' in self.config['LOGS']:
                self.log_dir = self.config['LOGS']['log_dir']
                # Ensure log directory exists
                os.makedirs(self.log_dir, exist_ok=True)
            
            # Get list of existing log files
            log_files = self.list_log_files()
            
            # If we have more logs than we want to keep, delete the oldest ones
            if len(log_files) > keep_logs:
                files_to_delete = log_files[:-keep_logs]
                logger.info(f"Deleting {len(files_to_delete)} old log files")
                
                for file_path in files_to_delete:
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted old log file: {file_path}")
                    except Exception as e:
                        logger.error(f"Error deleting log file {file_path}: {e}")
            else:
                logger.info(f"No old log files to delete (have {len(log_files)}, keeping {keep_logs})")
                
        except Exception as e:
            logger.error(f"Error during log rotation: {e}")
    
    def load_config_from_env(self) -> Dict[str, Any]:
        """
        Load configuration from environment variables.
        
        Returns:
            Dict[str, Any]: Configuration dictionary loaded from environment variables
        """
        env_config = {}
        
        # SYSTEM section
        if os.environ.get('BACKITUP_SERVER_NAME'):
            env_config.setdefault('SYSTEM', {})
            env_config['SYSTEM']['server_name'] = os.environ.get('BACKITUP_SERVER_NAME')
        
        # COMMANDS section
        commands_keys = {
            'BACKITUP_PRE_BACKUP_COMMAND': 'pre_backup',
            'BACKITUP_POST_BACKUP_COMMAND': 'post_backup',
            'BACKITUP_POST_TRANSFER_COMMAND': 'post_transfer'
        }
        
        for env_key, config_key in commands_keys.items():
            if os.environ.get(env_key):
                env_config.setdefault('COMMANDS', {})
                env_config['COMMANDS'][config_key] = os.environ.get(env_key)
        
        # DB section
        db_keys = {
            'BACKITUP_DB_TYPE': 'db_type',
            'BACKITUP_DB_HOST': 'db_host',
            'BACKITUP_DB_USER': 'db_user',
            'BACKITUP_DB_PASSWORD': 'db_password',
            'BACKITUP_DB_NAME': 'db_name'
        }
        
        for env_key, config_key in db_keys.items():
            if os.environ.get(env_key):
                env_config.setdefault('DB', {})
                env_config['DB'][config_key] = os.environ.get(env_key)
        
        # FILES section
        if os.environ.get('BACKITUP_FILES_DIR_PATH'):
            env_config.setdefault('FILES', {})
            env_config['FILES']['files_dir_path'] = os.environ.get('BACKITUP_FILES_DIR_PATH')
        
        # BACKUP section
        backup_keys = {
            'BACKITUP_DESTINATION_TYPE': 'destination_type',
            'BACKITUP_KEEP_LOCAL_COPY': 'keep_local_copy',
            'BACKITUP_KEEP_BACKUPS': 'keep_backups'
        }
        
        for env_key, config_key in backup_keys.items():
            if os.environ.get(env_key):
                env_config.setdefault('BACKUP', {})
                # Convert string to boolean for keep_local_copy
                if config_key == 'keep_local_copy':
                    env_config['BACKUP'][config_key] = os.environ.get(env_key).lower() in ('true', 'yes', '1')
                # Convert string to int for keep_backups
                elif config_key == 'keep_backups':
                    try:
                        env_config['BACKUP'][config_key] = int(os.environ.get(env_key))
                    except ValueError:
                        logger.warning(f"Invalid value for {env_key}: {os.environ.get(env_key)}. Using default.")
                else:
                    env_config['BACKUP'][config_key] = os.environ.get(env_key)
        
        # LOGS section
        logs_keys = {
            'BACKITUP_KEEP_LOGS': 'keep_logs',
            'BACKITUP_LOG_DIR': 'log_dir'
        }
        
        for env_key, config_key in logs_keys.items():
            if os.environ.get(env_key):
                env_config.setdefault('LOGS', {})
                # Convert string to int for keep_logs
                try:
                    env_config['LOGS'][config_key] = int(os.environ.get(env_key))
                except ValueError:
                    logger.warning(f"Invalid value for {env_key}: {os.environ.get(env_key)}. Using default.")
        
        # FTP section
        ftp_keys = {
            'BACKITUP_FTP_HOST': 'host',
            'BACKITUP_FTP_PORT': 'port',
            'BACKITUP_FTP_USERNAME': 'username',
            'BACKITUP_FTP_PASSWORD': 'password',
            'BACKITUP_FTP_REMOTE_DIR': 'remote_dir',
            'BACKITUP_FTP_PASSIVE_MODE': 'passive_mode'
        }
        
        for env_key, config_key in ftp_keys.items():
            if os.environ.get(env_key):
                env_config.setdefault('FTP', {})
                # Convert string to int for port
                if config_key == 'port':
                    try:
                        env_config['FTP'][config_key] = int(os.environ.get(env_key))
                    except ValueError:
                        logger.warning(f"Invalid value for {env_key}: {os.environ.get(env_key)}. Using default.")
                # Convert string to boolean for passive_mode
                elif config_key == 'passive_mode':
                    env_config['FTP'][config_key] = os.environ.get(env_key).lower() in ('true', 'yes', '1')
                else:
                    env_config['FTP'][config_key] = os.environ.get(env_key)
        
        # SFTP section
        sftp_keys = {
            'BACKITUP_SFTP_HOST': 'host',
            'BACKITUP_SFTP_PORT': 'port',
            'BACKITUP_SFTP_USERNAME': 'username',
            'BACKITUP_SFTP_PASSWORD': 'password',
            'BACKITUP_SFTP_PRIVATE_KEY_PATH': 'private_key_path',
            'BACKITUP_SFTP_REMOTE_DIR': 'remote_dir'
        }
        
        for env_key, config_key in sftp_keys.items():
            if os.environ.get(env_key):
                env_config.setdefault('SFTP', {})
                # Convert string to int for port
                if config_key == 'port':
                    try:
                        env_config['SFTP'][config_key] = int(os.environ.get(env_key))
                    except ValueError:
                        logger.warning(f"Invalid value for {env_key}: {os.environ.get(env_key)}. Using default.")
                else:
                    env_config['SFTP'][config_key] = os.environ.get(env_key)
        
        if env_config:
            logger.info("Loaded configuration from environment variables")
        
        return env_config
    
    def merge_configs(self, yaml_config: Dict[str, Any], env_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge YAML configuration with environment variables configuration.
        Environment variables take precedence over YAML configuration.
        
        Args:
            yaml_config: Configuration dictionary loaded from YAML file
            env_config: Configuration dictionary loaded from environment variables
            
        Returns:
            Dict[str, Any]: Merged configuration dictionary
        """
        # Start with a copy of the YAML config
        merged_config = yaml_config.copy() if yaml_config else {}
        
        # Merge environment variables config, giving it precedence
        for section, section_config in env_config.items():
            if section not in merged_config:
                merged_config[section] = {}
            
            for key, value in section_config.items():
                merged_config[section][key] = value
        
        return merged_config
    
    def validate_config(self) -> bool:
        """
        Validate the configuration from YAML file and/or environment variables.
        
        Returns:
            bool: True if configuration is valid, False otherwise
        """
        try:
            yaml_config = {}
            
            # Load YAML configuration if file exists
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as file:
                    yaml_config = yaml.safe_load(file) or {}
                logger.info(f"Loaded configuration from {self.config_path}")
            else:
                logger.info(f"Configuration file not found: {self.config_path}. Will try to use environment variables.")
            
            # Load environment variables configuration
            env_config = self.load_config_from_env()
            
            # Merge configurations, with environment variables taking precedence
            self.config = self.merge_configs(yaml_config, env_config)
            
            # If no configuration was loaded, return False
            if not self.config:
                logger.error("No configuration found in YAML file or environment variables")
                return False
            
            # Validate required fields
            required_db_fields = ['db_type', 'db_host']
            required_files_fields = ['files_dir_path']
            required_system_fields = ['server_name']
            required_backup_fields = ['destination_type']
            
            # Check SYSTEM section
            if 'SYSTEM' not in self.config:
                logger.error("Missing 'SYSTEM' section in configuration")
                return False
                
            for field in required_system_fields:
                if field not in self.config['SYSTEM']:
                    logger.error(f"Missing required field '{field}' in SYSTEM section")
                    return False
            
            # Update server_name from config
            self.server_name = self.config['SYSTEM']['server_name']
            logger.info(f"Using server name: {self.server_name}")
            
            # Update log_dir from config if specified
            if 'LOGS' in self.config and 'log_dir' in self.config['LOGS']:
                self.log_dir = self.config['LOGS']['log_dir']
                # Ensure log directory exists
                os.makedirs(self.log_dir, exist_ok=True)
                logger.info(f"Using log directory: {self.log_dir}")
            
            # Check BACKUP section (optional)
            if 'BACKUP' in self.config:
                for field in required_backup_fields:
                    if field not in self.config['BACKUP']:
                        logger.error(f"Missing required field '{field}' in BACKUP section")
                        return False
                
                # Validate destination_type
                valid_destination_types = ['local', 'ftp', 'sftp']
                destination_type = self.config['BACKUP']['destination_type']
                if destination_type not in valid_destination_types:
                    logger.error(f"Invalid destination_type: {destination_type}. Must be one of {valid_destination_types}")
                    return False
                
                # Validate FTP configuration if destination_type is ftp
                if destination_type == 'ftp':
                    if 'FTP' not in self.config:
                        logger.error("Missing 'FTP' section in configuration when destination_type is 'ftp'")
                        return False
                    
                    required_ftp_fields = ['host', 'username', 'password', 'remote_dir']
                    for field in required_ftp_fields:
                        if field not in self.config['FTP']:
                            logger.error(f"Missing required field '{field}' in FTP section")
                            return False
                
                # Validate SFTP configuration if destination_type is sftp
                if destination_type == 'sftp':
                    if not PARAMIKO_AVAILABLE:
                        logger.error("SFTP destination type selected but paramiko module is not available")
                        return False
                        
                    if 'SFTP' not in self.config:
                        logger.error("Missing 'SFTP' section in configuration when destination_type is 'sftp'")
                        return False
                    
                    required_sftp_fields = ['host', 'username', 'remote_dir']
                    for field in required_sftp_fields:
                        if field not in self.config['SFTP']:
                            logger.error(f"Missing required field '{field}' in SFTP section")
                            return False
                    
                    # Check if either password or private_key_path is provided
                    if not self.config['SFTP'].get('password') and not self.config['SFTP'].get('private_key_path'):
                        logger.error("Either 'password' or 'private_key_path' must be provided in SFTP section")
                        return False
                    
                    # Check if private key file exists
                    if self.config['SFTP'].get('private_key_path') and not os.path.exists(self.config['SFTP']['private_key_path']):
                        logger.error(f"SFTP private key file not found: {self.config['SFTP']['private_key_path']}")
                        return False
            
            # Check DB section
            if 'DB' not in self.config:
                logger.error("Missing 'DB' section in configuration")
                return False
                
            for field in required_db_fields:
                if field not in self.config['DB']:
                    logger.error(f"Missing required field '{field}' in DB section")
                    return False
            
            # Validate db_type
            valid_db_types = ['mysql', 'mariadb']
            if self.config['DB']['db_type'] not in valid_db_types:
                logger.error(f"Invalid db_type: {self.config['DB']['db_type']}. Must be one of {valid_db_types}")
                return False
            
            # Check FILES section
            if 'FILES' not in self.config:
                logger.error("Missing 'FILES' section in configuration")
                return False
                
            for field in required_files_fields:
                if field not in self.config['FILES']:
                    logger.error(f"Missing required field '{field}' in FILES section")
                    return False
            
            # Check if files directory exists
            files_dir = self.config['FILES']['files_dir_path']
            if not os.path.exists(files_dir):
                logger.error(f"Files directory does not exist: {files_dir}")
                return False
                
            return True
            
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration: {e}")
            return False
        except Exception as e:
            logger.error(f"Error validating configuration: {e}")
            return False
    
    def backup_database(self) -> Optional[str]:
        """
        Create a backup of the database using mysqldump and compress it.
        
        Returns:
            Optional[str]: Path to the compressed database backup file, or None if backup failed
        """
        try:
            db_type = self.config['DB']['db_type']
            db_host = self.config['DB']['db_host']
            
            # Get additional database parameters if available
            db_user = self.config['DB'].get('db_user', 'root')
            db_password = self.config['DB'].get('db_password', '')
            db_name = self.config['DB'].get('db_name', '--all-databases')
            
            # Create filename for the database backup
            backup_filename = f"{self.timestamp}_{self.server_name}_db.tar.gz"
            backup_path = os.path.join(self.temp_dir, backup_filename)
            
            # Create temporary SQL dump file
            dump_file = os.path.join(self.temp_dir, "database_dump.sql")
            
            # Build mysqldump command
            mysqldump_cmd = ["mysqldump"]
            
            # Add credentials
            if db_password:
                mysqldump_cmd.extend(["-p" + db_password])
            
            mysqldump_cmd.extend([
                "-u", db_user,
                "-h", db_host
            ])
            
            # Add database name or --all-databases
            if db_name == '--all-databases':
                mysqldump_cmd.append(db_name)
            else:
                mysqldump_cmd.append(db_name)
            
            # Execute mysqldump and redirect output to file
            logger.info(f"Creating database dump from {db_host}")
            with open(dump_file, 'w') as f:
                # Hide password from logs by creating a log-safe command
                log_cmd = mysqldump_cmd.copy()
                if db_password:
                    password_index = log_cmd.index("-p" + db_password)
                    log_cmd[password_index] = "-p******"
                logger.info(f"Executing: {' '.join(log_cmd)}")
                
                result = subprocess.run(mysqldump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
                
            if result.returncode != 0:
                logger.error(f"Database dump failed: {result.stderr}")
                return None
                
            # Compress the SQL dump
            logger.info(f"Compressing database dump to {backup_path}")
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(dump_file, arcname=os.path.basename(dump_file))
            
            # Remove the temporary SQL dump
            os.remove(dump_file)
            
            logger.info(f"Database backup completed: {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Error creating database backup: {e}")
            return None
    
    def backup_files(self) -> Optional[str]:
        """
        Create a backup of the specified files directory and compress it.
        
        Returns:
            Optional[str]: Path to the compressed files backup, or None if backup failed
        """
        try:
            files_dir = self.config['FILES']['files_dir_path']
            
            # Create filename for the files backup
            backup_filename = f"{self.timestamp}_{self.server_name}_root_files.tar.gz"
            backup_path = os.path.join(self.temp_dir, backup_filename)
            
            logger.info(f"Creating backup of directory: {files_dir}")
            
            # Create tar.gz archive
            with tarfile.open(backup_path, "w:gz") as tar:
                # Add the directory to the archive
                tar.add(files_dir, arcname=os.path.basename(files_dir))
            
            logger.info(f"Files backup completed: {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Error creating files backup: {e}")
            return None
    
    def combine_backups(self, db_backup_path: str, files_backup_path: str) -> Optional[str]:
        """
        Combine database and files backups into a single archive.
        
        Args:
            db_backup_path: Path to the database backup file
            files_backup_path: Path to the files backup file
            
        Returns:
            Optional[str]: Path to the combined backup file, or None if combining failed
        """
        try:
            # Create filename for the combined backup
            combined_filename = f"{self.timestamp}_{self.server_name}_root_files_and_db.tar.gz"
            combined_path = os.path.join(os.getcwd(), combined_filename)
            
            logger.info(f"Combining backups into: {combined_path}")
            
            # Create tar.gz archive
            with tarfile.open(combined_path, "w:gz") as tar:
                # Add both backup files to the archive
                tar.add(db_backup_path, arcname=os.path.basename(db_backup_path))
                tar.add(files_backup_path, arcname=os.path.basename(files_backup_path))
            
            logger.info(f"Combined backup completed: {combined_path}")
            return combined_path
            
        except Exception as e:
            logger.error(f"Error combining backups: {e}")
            return None
    
    def list_local_backups(self) -> List[str]:
        """
        List all existing local backups for the current server.
        
        Returns:
            List[str]: List of backup file paths, sorted by date (oldest first)
        """
        try:
            # Get the directory where backups are stored
            backup_dir = os.getcwd()
            
            # Define the pattern for backup files
            pattern = f"*_{self.server_name}_root_files_and_db.tar.gz"
            
            # Find all matching files
            backup_files = glob.glob(os.path.join(backup_dir, pattern))
            
            # Sort files by modification time (oldest first)
            backup_files.sort(key=os.path.getmtime)
            
            logger.info(f"Found {len(backup_files)} existing local backups")
            return backup_files
        except Exception as e:
            logger.error(f"Error listing local backups: {e}")
            return []
    
    def list_remote_backups_ftp(self) -> List[str]:
        """
        List all existing backups on the FTP server for the current server.
        
        Returns:
            List[str]: List of backup file names, sorted by date (oldest first)
        """
        try:
            if 'BACKUP' not in self.config or self.config['BACKUP'].get('destination_type') != 'ftp':
                logger.warning("FTP destination not configured, skipping remote backup listing")
                return []
                
            ftp_config = self.config['FTP']
            host = ftp_config['host']
            port = ftp_config.get('port', 21)
            username = ftp_config['username']
            password = ftp_config['password']
            remote_dir = ftp_config['remote_dir']
            passive_mode = ftp_config.get('passive_mode', True)
            
            logger.info(f"Connecting to FTP server to list backups: {host}:{port}")
            
            # Connect to FTP server
            ftp = ftplib.FTP()
            ftp.connect(host, port)
            ftp.login(username, password)
            
            if passive_mode:
                ftp.set_pasv(True)
            
            # Navigate to remote directory
            try:
                ftp.cwd(remote_dir)
            except ftplib.error_perm:
                logger.error(f"Remote directory {remote_dir} not found")
                ftp.quit()
                return []
            
            # List files in the directory
            file_list = []
            
            def append_file(filename):
                if f"_{self.server_name}_root_files_and_db.tar.gz" in filename:
                    file_list.append(filename)
            
            ftp.retrlines('LIST', append_file)
            
            # Extract just the filenames and sort by date (assuming YYYY-MM-DD.HH:MM prefix)
            backup_files = []
            for item in file_list:
                parts = item.split()
                if len(parts) >= 9:  # Standard Unix ls format
                    filename = parts[8]
                    if f"_{self.server_name}_root_files_and_db.tar.gz" in filename:
                        backup_files.append(filename)
            
            # Sort files by date prefix
            backup_files.sort()
            
            # Close the connection
            ftp.quit()
            
            logger.info(f"Found {len(backup_files)} existing remote backups on FTP server")
            return backup_files
            
        except Exception as e:
            logger.error(f"Error listing remote backups on FTP server: {e}")
            return []
    
    def list_remote_backups_sftp(self) -> List[str]:
        """
        List all existing backups on the SFTP server for the current server.
        
        Returns:
            List[str]: List of backup file names, sorted by date (oldest first)
        """
        try:
            if not PARAMIKO_AVAILABLE:
                logger.error("Paramiko module not available, cannot list SFTP backups")
                return []
                
            if 'BACKUP' not in self.config or self.config['BACKUP'].get('destination_type') != 'sftp':
                logger.warning("SFTP destination not configured, skipping remote backup listing")
                return []
                
            sftp_config = self.config['SFTP']
            host = sftp_config['host']
            port = sftp_config.get('port', 22)
            username = sftp_config['username']
            password = sftp_config.get('password', '')
            private_key_path = sftp_config.get('private_key_path', '')
            remote_dir = sftp_config['remote_dir']
            
            logger.info(f"Connecting to SFTP server to list backups: {host}:{port}")
            
            # Connect to SFTP server
            transport = paramiko.Transport((host, port))
            
            if private_key_path:
                private_key = paramiko.RSAKey.from_private_key_file(private_key_path)
                transport.connect(username=username, pkey=private_key)
            else:
                transport.connect(username=username, password=password)
            
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Check if remote directory exists
            try:
                sftp.stat(remote_dir)
            except IOError:
                logger.error(f"Remote directory {remote_dir} not found")
                sftp.close()
                transport.close()
                return []
            
            # List files in the directory
            file_list = sftp.listdir(remote_dir)
            
            # Filter and sort backup files
            backup_files = [f for f in file_list if f"_{self.server_name}_root_files_and_db.tar.gz" in f]
            backup_files.sort()
            
            # Close the connection
            sftp.close()
            transport.close()
            
            logger.info(f"Found {len(backup_files)} existing remote backups on SFTP server")
            return backup_files
            
        except Exception as e:
            logger.error(f"Error listing remote backups on SFTP server: {e}")
            return []
    
    def delete_old_local_backups(self):
        """
        Delete old local backups, keeping only the specified number of most recent backups.
        """
        try:
            if 'BACKUP' not in self.config or not self.config['BACKUP'].get('keep_local_copy', True):
                logger.info("Local backups not configured to be kept, skipping rotation")
                return
            
            keep_backups = self.config['BACKUP'].get('keep_backups', 0)
            if keep_backups <= 0:
                logger.info("Backup rotation disabled (keep_backups <= 0)")
                return
            
            # Get list of existing backups
            backup_files = self.list_local_backups()
            
            # If we have more backups than we want to keep, delete the oldest ones
            if len(backup_files) > keep_backups:
                files_to_delete = backup_files[:-keep_backups]
                logger.info(f"Deleting {len(files_to_delete)} old local backups")
                
                for file_path in files_to_delete:
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted old backup: {file_path}")
                    except Exception as e:
                        logger.error(f"Error deleting backup {file_path}: {e}")
            else:
                logger.info(f"No old local backups to delete (have {len(backup_files)}, keeping {keep_backups})")
                
        except Exception as e:
            logger.error(f"Error during local backup rotation: {e}")
    
    def delete_old_remote_backups_ftp(self):
        """
        Delete old backups on the FTP server, keeping only the specified number of most recent backups.
        """
        try:
            if 'BACKUP' not in self.config or self.config['BACKUP'].get('destination_type') != 'ftp':
                logger.info("FTP destination not configured, skipping remote backup rotation")
                return
            
            keep_backups = self.config['BACKUP'].get('keep_backups', 0)
            if keep_backups <= 0:
                logger.info("Backup rotation disabled (keep_backups <= 0)")
                return
            
            # Get FTP configuration
            ftp_config = self.config['FTP']
            host = ftp_config['host']
            port = ftp_config.get('port', 21)
            username = ftp_config['username']
            password = ftp_config['password']
            remote_dir = ftp_config['remote_dir']
            passive_mode = ftp_config.get('passive_mode', True)
            
            # Get list of existing backups
            backup_files = self.list_remote_backups_ftp()
            
            # If we have more backups than we want to keep, delete the oldest ones
            if len(backup_files) > keep_backups:
                files_to_delete = backup_files[:-keep_backups]
                logger.info(f"Deleting {len(files_to_delete)} old remote backups from FTP server")
                
                # Connect to FTP server
                ftp = ftplib.FTP()
                ftp.connect(host, port)
                ftp.login(username, password)
                
                if passive_mode:
                    ftp.set_pasv(True)
                
                # Navigate to remote directory
                try:
                    ftp.cwd(remote_dir)
                except ftplib.error_perm:
                    logger.error(f"Remote directory {remote_dir} not found")
                    ftp.quit()
                    return
                
                # Delete old backups
                for filename in files_to_delete:
                    try:
                        ftp.delete(filename)
                        logger.info(f"Deleted old backup from FTP server: {filename}")
                    except Exception as e:
                        logger.error(f"Error deleting backup {filename} from FTP server: {e}")
                
                # Close the connection
                ftp.quit()
            else:
                logger.info(f"No old remote backups to delete from FTP server (have {len(backup_files)}, keeping {keep_backups})")
                
        except Exception as e:
            logger.error(f"Error during FTP backup rotation: {e}")
    
    def delete_old_remote_backups_sftp(self):
        """
        Delete old backups on the SFTP server, keeping only the specified number of most recent backups.
        """
        try:
            if not PARAMIKO_AVAILABLE:
                logger.error("Paramiko module not available, cannot rotate SFTP backups")
                return
                
            if 'BACKUP' not in self.config or self.config['BACKUP'].get('destination_type') != 'sftp':
                logger.info("SFTP destination not configured, skipping remote backup rotation")
                return
            
            keep_backups = self.config['BACKUP'].get('keep_backups', 0)
            if keep_backups <= 0:
                logger.info("Backup rotation disabled (keep_backups <= 0)")
                return
            
            # Get SFTP configuration
            sftp_config = self.config['SFTP']
            host = sftp_config['host']
            port = sftp_config.get('port', 22)
            username = sftp_config['username']
            password = sftp_config.get('password', '')
            private_key_path = sftp_config.get('private_key_path', '')
            remote_dir = sftp_config['remote_dir']
            
            # Get list of existing backups
            backup_files = self.list_remote_backups_sftp()
            
            # If we have more backups than we want to keep, delete the oldest ones
            if len(backup_files) > keep_backups:
                files_to_delete = backup_files[:-keep_backups]
                logger.info(f"Deleting {len(files_to_delete)} old remote backups from SFTP server")
                
                # Connect to SFTP server
                transport = paramiko.Transport((host, port))
                
                if private_key_path:
                    private_key = paramiko.RSAKey.from_private_key_file(private_key_path)
                    transport.connect(username=username, pkey=private_key)
                else:
                    transport.connect(username=username, password=password)
                
                sftp = paramiko.SFTPClient.from_transport(transport)
                
                # Delete old backups
                for filename in files_to_delete:
                    try:
                        sftp.remove(os.path.join(remote_dir, filename))
                        logger.info(f"Deleted old backup from SFTP server: {filename}")
                    except Exception as e:
                        logger.error(f"Error deleting backup {filename} from SFTP server: {e}")
                
                # Close the connection
                sftp.close()
                transport.close()
            else:
                logger.info(f"No old remote backups to delete from SFTP server (have {len(backup_files)}, keeping {keep_backups})")
                
        except Exception as e:
            logger.error(f"Error during SFTP backup rotation: {e}")
    
    def rotate_backups(self):
        """
        Rotate backups based on the configuration, deleting old backups as needed.
        """
        try:
            # Rotate local backups
            self.delete_old_local_backups()
            
            # Rotate remote backups based on destination type
            if 'BACKUP' in self.config:
                destination_type = self.config['BACKUP'].get('destination_type', 'local')
                
                if destination_type == 'ftp':
                    self.delete_old_remote_backups_ftp()
                elif destination_type == 'sftp':
                    self.delete_old_remote_backups_sftp()
                    
        except Exception as e:
            logger.error(f"Error during backup rotation: {e}")
    
    def send_to_ftp(self, backup_path: str) -> bool:
        """
        Send the backup file to an FTP server.
        
        Args:
            backup_path: Path to the backup file to send
            
        Returns:
            bool: True if the upload was successful, False otherwise
        """
        try:
            if 'BACKUP' not in self.config or self.config['BACKUP'].get('destination_type') != 'ftp':
                logger.warning("FTP destination not configured, skipping upload")
                return False
                
            ftp_config = self.config['FTP']
            host = ftp_config['host']
            port = ftp_config.get('port', 21)
            username = ftp_config['username']
            password = ftp_config['password']
            remote_dir = ftp_config['remote_dir']
            passive_mode = ftp_config.get('passive_mode', True)
            
            logger.info(f"Connecting to FTP server: {host}:{port}")
            
            # Connect to FTP server
            ftp = ftplib.FTP()
            ftp.connect(host, port)
            ftp.login(username, password)
            
            if passive_mode:
                ftp.set_pasv(True)
            
            # Navigate to remote directory, create if it doesn't exist
            try:
                ftp.cwd(remote_dir)
            except ftplib.error_perm:
                # Try to create the directory
                logger.info(f"Remote directory {remote_dir} not found, attempting to create it")
                
                # Create directories recursively
                current_dir = ""
                for part in remote_dir.strip('/').split('/'):
                    if part:
                        current_dir += f"/{part}"
                        try:
                            ftp.cwd(current_dir)
                        except ftplib.error_perm:
                            ftp.mkd(current_dir)
                            ftp.cwd(current_dir)
            
            # Upload the file
            backup_filename = os.path.basename(backup_path)
            logger.info(f"Uploading {backup_filename} to FTP server")
            
            with open(backup_path, 'rb') as file:
                ftp.storbinary(f'STOR {backup_filename}', file)
            
            # Close the connection
            ftp.quit()
            
            logger.info(f"Successfully uploaded {backup_filename} to FTP server")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading to FTP server: {e}")
            return False
    
    def send_to_sftp(self, backup_path: str) -> bool:
        """
        Send the backup file to an SFTP server.
        
        Args:
            backup_path: Path to the backup file to send
            
        Returns:
            bool: True if the upload was successful, False otherwise
        """
        try:
            if not PARAMIKO_AVAILABLE:
                logger.error("Paramiko module not available, cannot use SFTP")
                return False
                
            if 'BACKUP' not in self.config or self.config['BACKUP'].get('destination_type') != 'sftp':
                logger.warning("SFTP destination not configured, skipping upload")
                return False
                
            sftp_config = self.config['SFTP']
            host = sftp_config['host']
            port = sftp_config.get('port', 22)
            username = sftp_config['username']
            password = sftp_config.get('password', '')
            private_key_path = sftp_config.get('private_key_path', '')
            remote_dir = sftp_config['remote_dir']
            
            logger.info(f"Connecting to SFTP server: {host}:{port}")
            
            # Connect to SFTP server
            transport = paramiko.Transport((host, port))
            
            if private_key_path:
                private_key = paramiko.RSAKey.from_private_key_file(private_key_path)
                transport.connect(username=username, pkey=private_key)
            else:
                transport.connect(username=username, password=password)
            
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Navigate to remote directory, create if it doesn't exist
            try:
                sftp.stat(remote_dir)
            except IOError:
                # Try to create the directory
                logger.info(f"Remote directory {remote_dir} not found, attempting to create it")
                
                # Create directories recursively
                current_dir = ""
                for part in remote_dir.strip('/').split('/'):
                    if part:
                        current_dir += f"/{part}"
                        try:
                            sftp.stat(current_dir)
                        except IOError:
                            sftp.mkdir(current_dir)
            
            # Upload the file
            backup_filename = os.path.basename(backup_path)
            remote_path = f"{remote_dir}/{backup_filename}"
            logger.info(f"Uploading {backup_filename} to SFTP server")
            
            sftp.put(backup_path, remote_path)
            
            # Close the connection
            sftp.close()
            transport.close()
            
            logger.info(f"Successfully uploaded {backup_filename} to SFTP server")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading to SFTP server: {e}")
            return False
    
    def send_backup(self, backup_path: str) -> bool:
        """
        Send the backup file to the configured destination.
        
        Args:
            backup_path: Path to the backup file to send
            
        Returns:
            bool: True if the upload was successful or not needed, False otherwise
        """
        if 'BACKUP' not in self.config:
            logger.info("No backup destination configured, keeping local copy only")
            return True
            
        destination_type = self.config['BACKUP'].get('destination_type', 'local')
        
        if destination_type == 'local':
            logger.info("Local destination configured, keeping local copy only")
            return True
        elif destination_type == 'ftp':
            return self.send_to_ftp(backup_path)
        elif destination_type == 'sftp':
            return self.send_to_sftp(backup_path)
        else:
            logger.error(f"Unknown destination type: {destination_type}")
            return False
    
    def execute_command(self, command_type: str) -> bool:
        """
        Execute a command from the configuration.
        
        Args:
            command_type: Type of command to execute ('pre_backup', 'post_backup', or 'post_transfer')
            
        Returns:
            bool: True if command execution was successful or no command was configured, False otherwise
        """
        try:
            if 'COMMANDS' not in self.config or not self.config['COMMANDS'].get(command_type):
                logger.info(f"No {command_type} command configured, skipping execution")
                return True
                
            command = self.config['COMMANDS'][command_type]
            logger.info(f"Executing {command_type} command: {command}")
            
            result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            if result.returncode != 0:
                logger.error(f"{command_type} command failed with exit code {result.returncode}: {result.stderr}")
                return False
                
            logger.info(f"{command_type} command executed successfully")
            if result.stdout:
                logger.info(f"{command_type} command output: {result.stdout}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error executing {command_type} command: {e}")
            return False
    
    def cleanup(self, backup_path: str = None):
        """
        Remove temporary files and directories.
        
        Args:
            backup_path: Path to the backup file to remove if not keeping local copy
        """
        try:
            # Clean up temp directory
            logger.info(f"Cleaning up temporary directory: {self.temp_dir}")
            shutil.rmtree(self.temp_dir)
            
            # Remove local backup if configured not to keep it
            if (backup_path and 'BACKUP' in self.config and 
                not self.config['BACKUP'].get('keep_local_copy', True) and
                self.config['BACKUP'].get('destination_type') != 'local'):
                logger.info(f"Removing local backup: {backup_path}")
                os.remove(backup_path)
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def run(self) -> bool:
        """
        Run the backup process.
        
        Returns:
            bool: True if backup was successful, False otherwise
        """
        # Validate configuration
        if not self.validate_config():
            logger.error("Configuration validation failed. Aborting backup.")
            return False
            
        # Set up logging with the configured log directory
        self.setup_logging()
        
        # Execute pre-backup command
        if not self.execute_command('pre_backup'):
            logger.error("Pre-backup command failed. Aborting backup.")
            return False
        
        # Backup database
        db_backup_path = self.backup_database()
        if not db_backup_path:
            logger.error("Database backup failed. Aborting backup.")
            self.cleanup()
            return False
        
        # Backup files
        files_backup_path = self.backup_files()
        if not files_backup_path:
            logger.error("Files backup failed. Aborting backup.")
            self.cleanup()
            return False
        
        # Combine backups
        combined_path = self.combine_backups(db_backup_path, files_backup_path)
        if not combined_path:
            logger.error("Failed to combine backups.")
            self.cleanup()
            return False
        
        # Execute post-backup command
        if not self.execute_command('post_backup'):
            logger.error("Post-backup command failed. Continuing with backup process.")
        
        # Send backup to configured destination
        upload_success = self.send_backup(combined_path)
        if not upload_success and 'BACKUP' in self.config and self.config['BACKUP'].get('destination_type') != 'local':
            logger.error("Failed to upload backup to remote destination.")
            # Continue with cleanup, but return failure
        
        # Rotate old backups
        self.rotate_backups()
        
        # Cleanup
        self.cleanup(combined_path)
        
        if not upload_success and 'BACKUP' in self.config and self.config['BACKUP'].get('destination_type') != 'local':
            return False
        
        # Execute post-transfer command
        if not self.execute_command('post_transfer'):
            logger.error("Post-transfer command failed.")
        
        # Rotate log files
        self.rotate_logs()
        
        logger.info(f"Backup process completed successfully. Final backup: {combined_path}")
        return True


def main():
    """Main function to run the backup agent"""
    # Get configuration file path from command line argument or use default
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    
    logger.info(f"Starting backup agent with configuration: {config_path}")
    
    # Create and run backup agent
    agent = BackupAgent(config_path)
    success = agent.run()
    
    # Exit with appropriate status code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
