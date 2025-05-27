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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backup.log"),
        logging.StreamHandler()
    ]
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
            config_path: Path to the YAML configuration file
        """
        self.config_path = config_path
        self.config = None
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d.%H:%M")
        # Default server name from system, may be overridden by config
        self.server_name = os.uname().nodename
        self.temp_dir = f"/tmp/backup_{self.timestamp}"
        
        # Ensure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
    def validate_config(self) -> bool:
        """
        Validate the YAML configuration file.
        
        Returns:
            bool: True if configuration is valid, False otherwise
        """
        try:
            # Check if config file exists
            if not os.path.exists(self.config_path):
                logger.error(f"Configuration file not found: {self.config_path}")
                return False
                
            # Load and parse YAML
            with open(self.config_path, 'r') as file:
                self.config = yaml.safe_load(file)
            
            logger.info(f"Loaded configuration from {self.config_path}")
            
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
