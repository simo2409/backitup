# backItUp: a Linux Server Backup Agent

A Python-based backup agent for Linux servers that creates backups of MySQL/MariaDB databases and specified file directories.

## Features

- Backs up MySQL/MariaDB databases using mysqldump
- Backs up specified file directories
- Compresses backups into tar.gz files
- Creates a combined archive containing both database and files backups
- Executes custom commands at key points in the backup process
- Validates configuration before proceeding
- Detailed logging
- Supports uploading backups to FTP or SFTP servers

## Requirements

- Python 3.6+
- PyYAML package
- MySQL/MariaDB client tools (mysqldump)
- For SFTP support: paramiko package (optional)

## Installation

1. Copy the `backitup.py` and `config.yaml` files to your server
2. Install required Python packages:

```bash
pip install pyyaml
```

3. For SFTP support, install the paramiko package:

```bash
pip install paramiko
```

4. Make the script executable:

```bash
chmod +x backitup.py
```

## Configuration

You can configure the backup agent using either a YAML configuration file, environment variables, or a combination of both. If a configuration option is specified in both the YAML file and environment variables, the environment variable takes precedence.

### YAML Configuration

Edit the `config.yaml` file to match your server's configuration:

```yaml
# System Configuration
SYSTEM:
  server_name: "foobar.com"  # Server name to use in backup filenames

# Database Configuration
DB:
  db_type: "mysql"  # Can be "mysql" or "mariadb"
  db_host: "127.0.0.1"
  db_user: "root"  # Optional, defaults to "root"
  db_password: ""  # Optional, defaults to empty string
  db_name: "--all-databases"  # Optional, defaults to "--all-databases"

# Files Configuration
FILES:
  files_dir_path: "/var/www/something/current"

# Command Execution Configuration
COMMANDS:
  pre_backup: "echo 'Starting backup' | mail -s 'Backup started' admin@example.com"    # Command to execute before beginning backup operations
  post_backup: "echo 'Backup created, preparing to transfer' | mail -s 'Backup ready' admin@example.com"   # Command to execute after backup operations but before transfer
  post_transfer: "echo 'Backup completed and transferred' | mail -s 'Backup completed' admin@example.com" # Command to execute after all operations including transfer

# Backup Destination Configuration
BACKUP:
  destination_type: "ftp"  # Can be "ftp", "sftp", or "local" (default)
  keep_local_copy: true    # Whether to keep a local copy after uploading
  keep_backups: 5          # Number of backups to preserve (older ones will be deleted)

# Logs Configuration
LOGS:
  keep_logs: 5             # Number of log files to preserve (older ones will be deleted)
  log_dir: "logs"          # Directory to store log files (will be created if it doesn't exist)

# FTP Configuration (used when destination_type is "ftp")
FTP:
  host: "ftp.example.com"
  port: 21
  username: "ftpuser"
  password: "ftppassword"
  remote_dir: "/backups"
  passive_mode: true

# SFTP Configuration (used when destination_type is "sftp")
SFTP:
  host: "sftp.example.com"
  port: 22
  username: "sftpuser"
  password: ""  # Leave empty if using key-based authentication
  private_key_path: "/path/to/private/key"  # Path to private key for authentication
  remote_dir: "/backups"
```

### Environment Variables Configuration

You can also configure the backup agent using environment variables. This is useful for containerized environments or when you want to avoid storing sensitive information in configuration files.

The following environment variables are supported:

#### System Configuration
- `BACKITUP_SERVER_NAME`: Server name to use in backup filenames

#### Database Configuration
- `BACKITUP_DB_TYPE`: Database type, either "mysql" or "mariadb"
- `BACKITUP_DB_HOST`: Database host address
- `BACKITUP_DB_USER`: Database username
- `BACKITUP_DB_PASSWORD`: Database password
- `BACKITUP_DB_NAME`: Database name to backup

#### Files Configuration
- `BACKITUP_FILES_DIR_PATH`: Path to the directory to backup

#### Command Execution Configuration
- `BACKITUP_PRE_BACKUP_COMMAND`: Command to execute before beginning backup operations
- `BACKITUP_POST_BACKUP_COMMAND`: Command to execute after backup operations but before transfer
- `BACKITUP_POST_TRANSFER_COMMAND`: Command to execute after all operations including transfer

#### Backup Destination Configuration
- `BACKITUP_DESTINATION_TYPE`: Where to send the backup, can be "local", "ftp", or "sftp"
- `BACKITUP_KEEP_LOCAL_COPY`: Whether to keep a local copy of the backup after uploading (true/false)
- `BACKITUP_KEEP_BACKUPS`: Number of backups to preserve

#### Logs Configuration
- `BACKITUP_KEEP_LOGS`: Number of log files to preserve (older ones will be automatically deleted)
- `BACKITUP_LOG_DIR`: Directory to store log files (will be created if it doesn't exist)

#### FTP Configuration
- `BACKITUP_FTP_HOST`: FTP server hostname or IP address
- `BACKITUP_FTP_PORT`: FTP server port
- `BACKITUP_FTP_USERNAME`: FTP username
- `BACKITUP_FTP_PASSWORD`: FTP password
- `BACKITUP_FTP_REMOTE_DIR`: Directory on the FTP server to store backups
- `BACKITUP_FTP_PASSIVE_MODE`: Whether to use passive mode (true/false)

#### SFTP Configuration
- `BACKITUP_SFTP_HOST`: SFTP server hostname or IP address
- `BACKITUP_SFTP_PORT`: SFTP server port
- `BACKITUP_SFTP_USERNAME`: SFTP username
- `BACKITUP_SFTP_PASSWORD`: SFTP password
- `BACKITUP_SFTP_PRIVATE_KEY_PATH`: Path to the private key file
- `BACKITUP_SFTP_REMOTE_DIR`: Directory on the SFTP server to store backups

Example of setting environment variables:

```bash
# Set required environment variables
export BACKITUP_SERVER_NAME="foobar.com"
export BACKITUP_DB_TYPE="mysql"
export BACKITUP_DB_HOST="127.0.0.1"
export BACKITUP_FILES_DIR_PATH="/var/www/something/current"

# Set command execution (optional)
export BACKITUP_PRE_BACKUP_COMMAND="echo 'Starting backup' | mail -s 'Backup started' admin@example.com"
export BACKITUP_POST_BACKUP_COMMAND="echo 'Backup created, preparing to transfer' | mail -s 'Backup ready' admin@example.com"
export BACKITUP_POST_TRANSFER_COMMAND="rclone sync /path/to/backups remote:backup-folder --progress"

# Set log rotation (optional)
export BACKITUP_KEEP_LOGS=5
export BACKITUP_LOG_DIR="logs"

# Run the backup agent
./backitup.py
```

### Configuration Options

#### SYSTEM Section

- `server_name`: Name of the server to use in backup filenames

#### DB Section

- `db_type`: Database type, either "mysql" or "mariadb"
- `db_host`: Database host address
- `db_user`: (Optional) Database username, defaults to "root"
- `db_password`: (Optional) Database password, defaults to empty string
- `db_name`: (Optional) Database name to backup, defaults to "--all-databases" which backs up all databases

#### FILES Section

- `files_dir_path`: Path to the directory to backup

#### COMMANDS Section (Optional)

- `pre_backup`: Command to execute before beginning backup operations
- `post_backup`: Command to execute after backup operations but before transfer
- `post_transfer`: Command to execute after all operations including transfer

Example of using rclone to sync backups to cloud storage after all operations:

```bash
# In config.yaml
COMMANDS:
  post_transfer: "rclone sync /path/to/backups remote:backup-folder --progress"
```

This example uses rclone to synchronize your local backup directory with a configured remote storage (like Google Drive, Dropbox, AWS S3, etc.) after the backup and transfer operations are complete.

#### BACKUP Section (Optional)

- `destination_type`: Where to send the backup, can be "local", "ftp", or "sftp"
- `keep_local_copy`: Whether to keep a local copy of the backup after uploading to a remote destination
- `keep_backups`: Number of backups to preserve (older ones will be automatically deleted)

#### LOGS Section (Optional)

- `keep_logs`: Number of log files to preserve (older ones will be automatically deleted)
- `log_dir`: Directory to store log files (will be created if it doesn't exist)

#### FTP Section (Required when destination_type is "ftp")

- `host`: FTP server hostname or IP address
- `port`: (Optional) FTP server port, defaults to 21
- `username`: FTP username
- `password`: FTP password
- `remote_dir`: Directory on the FTP server to store backups
- `passive_mode`: (Optional) Whether to use passive mode, defaults to true

#### SFTP Section (Required when destination_type is "sftp")

- `host`: SFTP server hostname or IP address
- `port`: (Optional) SFTP server port, defaults to 22
- `username`: SFTP username
- `password`: SFTP password (required if not using key-based authentication)
- `private_key_path`: Path to the private key file (required if not using password authentication)
- `remote_dir`: Directory on the SFTP server to store backups

## Usage

Run the backup agent:

```bash
./backitup.py
```

Or specify a custom configuration file:

```bash
./backitup.py /path/to/custom-config.yaml
```

The configuration file is optional if all required configuration is provided through environment variables.

## Output

The backup agent creates a combined backup file in the current directory with the naming format:

```
[YYYY-MM-DD.HH:MM:SS]_[server_name]_root_files_and_db.tar.gz
```

This archive contains two files:
1. `[YYYY-MM-DD.HH:MM:SS]_[server_name]_db.tar.gz` - Database backup
2. `[YYYY-MM-DD.HH:MM:SS]_[server_name]_root_files.tar.gz` - Files backup

If a remote destination (FTP or SFTP) is configured, the backup will be uploaded to that destination. You can choose whether to keep a local copy of the backup after uploading by setting the `keep_local_copy` option in the BACKUP section.

The agent also supports backup rotation, which automatically deletes older backups while keeping a specified number of the most recent ones. This applies to both local and remote backups. Set the `keep_backups` option in the BACKUP section to specify how many backups to preserve.

## Logging

Logs are written to both the console and a log file in a dedicated logs directory. The log file is named with a timestamp prefix in the format `[YYYY-MM-DD.HH:MM:SS]_backup.log`.

The agent also supports log rotation, which automatically deletes older log files while keeping a specified number of the most recent ones. Set the `keep_logs` option in the LOGS section to specify how many log files to preserve. You can also specify a custom log directory using the `log_dir` option.

## Automation

To run the backup automatically, you can set up a cron job:

```bash
# Edit crontab
crontab -e

# Add a line to run the backup daily at 2 AM
0 2 * * * cd /path/to/backup/script && ./backitup.py
